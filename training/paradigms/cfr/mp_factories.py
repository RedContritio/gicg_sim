"""CFR mp-mode factories — env / opp registry / policy / provider / spec
sampler + a traversal-lifecycle Runner. Mirrors
``training.paradigms.ppo.mp_factories`` (DMC/PPO template, I31 backlog #88):
top-level spawn-safe factories resolved via dotted-path in the child, parent
owns the handoff. cfg-driven, no env var (``feedback_cfg_driven_only``): child
reconstructs ``CFRParadigmConfig.from_dict(cfg.paradigm)``.

CFR's lifecycle is **traversal** (double-sided recursive game-tree walk via
``CFRTraverser``), NOT episode — so CFR composes BOTH orthogonal actor_main
hatches: AB13 ``provider_kwargs`` (WeightsSHM + blueprint handoff, like PPO)
AND AB14 ``episode_runner_factory`` (:class:`CFRTraversalRunner`, since the
default ``EpisodeRunner`` cannot host a tree traversal).

D2=A WeightsSHM 2-slot handoff: per-player advantage nets → TWO named slots
``cfr_adv_p0`` / ``cfr_adv_p1`` (vs PPO's single ``latest``);
:class:`_CFRActorProvider` polls both, reloading on version bump (D3=C).
D1.B EpisodeSpec field-reuse (CFR-local convention, design.md §3 D1.B + §9
risk 2): traversal metadata encoded into existing :class:`EpisodeSpec` fields;
full schema on :func:`cfr_spec_sampler` (encode) / ``CFRTraversalRunner.run`` (decode).
"""

from __future__ import annotations

import pickle
import random
from dataclasses import dataclass, field
from typing import Any

from training.core.protocols import EpisodeSpec

OPP_SENTINEL = 'cfr_traverser'  # opponent_id sentinel — never registry-looked-up


def _derive_seed(master_seed: int, *labels: Any) -> int:
    h = master_seed & 0xFFFFFFFF
    for lab in labels:
        for b in repr(lab).encode('utf-8'):
            h = (h * 1000003) ^ b
            h &= 0xFFFFFFFF
    return int(h & 0x7FFFFFFF)


# ---------- spawn-safe top-level builders(actor_main resolves via dotted path) ---------- #


def build_env_factory(cfg: Any, seed: int):
    del seed
    from gicg_env import GicgEnv

    scen = cfg.scenario
    fd = list(scen.fix_dice) if getattr(scen, 'fix_dice', None) else None

    def _factory(scenario_seed: int):
        env = GicgEnv(
            list(scen.team_0),
            list(scen.team_1),
            card_pool=list(getattr(scen, 'card_pool', None) or ()),
            seed=int(scenario_seed),
            data_dir=str(getattr(scen, 'data_dir', 'data')),
            max_rounds=int(getattr(scen, 'max_rounds', 3)),
            fix_dice=fd,
            deck_padding=getattr(scen, 'deck_padding', None),
            pool=getattr(scen, 'pool', ['v_legacy', 'test_basic']),
        )
        env.reset(seed=int(scenario_seed))
        return env

    return _factory


def build_opp_registry(cfg: Any):
    """Empty registry — CFR traversal has no opponent (``CFRTraverser`` walks
    both sides); the ``'cfr_traverser'`` sentinel is never looked up. Returned
    non-None only to satisfy actor_main's required-builder validation."""
    del cfg
    from training.core.eval.baselines import OpponentRegistry

    return OpponentRegistry()


def build_policy(cfg: Any, actor_id: int):
    """``_CFRTraversalPolicy`` stub — CFR's runner drives the traverser directly,
    never stepping via ``policy.act``. Non-None only for actor_main validation."""
    del cfg, actor_id
    return _CFRTraversalPolicy()


def _build_net_and_traversal_cfg(cfg: Any):
    """(CFRNetConfig, TraversalConfig) from ``cfg.paradigm`` — same path as
    serial ``paradigm.make_network`` so mp == serial shapes."""
    from training.paradigms.cfr.config import CFRParadigmConfig
    from training.paradigms.cfr.strategy_net import CFRNetConfig
    from training.paradigms.cfr.traversal import TraversalConfig

    pcfg = CFRParadigmConfig.from_dict(cfg.paradigm)
    agent = pcfg.agent
    net_cfg = CFRNetConfig(
        n_counter_slots=agent.n_counter_slots,
        n_hooks=agent.n_hooks,
        max_ops_per_hook=agent.max_ops_per_hook,
        max_actions=agent.max_actions,
        d_model=agent.d_model,
        dropout=agent.dropout,
        n_cross_layers=agent.n_cross_layers,
    )
    trav_cfg = TraversalConfig(
        sampling_mode=pcfg.traversal.sampling_mode,
        epsilon=pcfg.traversal.epsilon,
        max_game_steps=pcfg.traversal.max_game_steps,
        importance_weight_max=pcfg.traversal.importance_weight_max,
    )
    return net_cfg, trav_cfg


def build_provider(cfg: Any, actor_id: int, *, weights_shm_info: dict, network_blueprint_path: str):
    """Per-actor provider — WeightsSHM.attach + 2 AdvantageNet + CFRTraverser.

    Spawn-safe kwargs (parent → child via ``provider_kwargs``, AB13):
    ``weights_shm_info`` = ``WeightsSHM.serialize_for_worker(['cfr_adv_p0',
    'cfr_adv_p1'])``; ``network_blueprint_path`` = tempfile of a pickled
    2-element cpu ``AdvantageNet`` list. Raises RuntimeError on a cold SHM slot
    or non-2-net blueprint. Collector buffers + traverser are built child-local
    — NOT pickled across spawn (only nets cross, via blueprint + SHM)."""
    import torch

    from gicg_env.engine import preload_dsl

    from training.core.actor.weights_shm import WeightsSHM
    from training.paradigms.cfr._collect_helpers import CollectorBuffer
    from training.paradigms.cfr.traversal import CFRTraverser

    # Eager DSL preload (worker.py:81 parity) — fill engine cache once per child.
    preload_dsl(str(getattr(cfg.scenario, 'data_dir', 'data')))

    with open(network_blueprint_path, 'rb') as f:
        nets = pickle.load(f)
    if not isinstance(nets, (list, tuple)) or len(nets) != 2:
        raise RuntimeError(f'CFRAsync: network blueprint must be 2 AdvantageNet, got {type(nets)!r} len={len(nets)}')
    nets = list(nets)

    shm = WeightsSHM.attach(weights_shm_info)
    versions = []
    for p in range(2):
        sd, ver = shm.read(f'cfr_adv_p{p}')
        if sd is None:
            raise RuntimeError(f'CFRAsync: WeightsSHM cfr_adv_p{p} cold — parent must publish both slots before spawn')
        nets[p].load_state_dict(sd)
        nets[p].eval()
        versions.append(int(ver))

    net_cfg, trav_cfg = _build_net_and_traversal_cfg(cfg)
    adv_cols = [CollectorBuffer(), CollectorBuffer()]
    strat_col = CollectorBuffer()
    val_col = CollectorBuffer()
    rng = random.Random(_derive_seed(int(cfg.meta.seed), 'cfr-actor', int(actor_id)))
    traverser = CFRTraverser(
        advantage_nets=nets,
        n_counter_slots=net_cfg.n_counter_slots,
        max_ops_per_hook=net_cfg.max_ops_per_hook,
        n_hooks_capacity=net_cfg.n_hooks,
        max_actions=net_cfg.max_actions,
        advantage_buffers=adv_cols,  # type: ignore[arg-type]
        strategy_buffer=strat_col,  # type: ignore[arg-type]
        value_buffer=val_col,  # type: ignore[arg-type]
        config=trav_cfg,
        rng=rng,
        device=torch.device('cpu'),
    )
    return _CFRActorProvider(nets, traverser, shm, adv_cols, strat_col, val_col, versions)


_SPEC_COUNTERS: dict = {}  # per-actor monotonic seq; per-process safe (each actor a spawned proc)


def _read_traverser_alternation(cfg: Any) -> str:
    """``cfg.paradigm['traversal']['traverser_alternation']`` (dict post-spawn;
    dataclass in some test paths). Default 'alternate' matches the cfg default."""
    trav = (cfg.paradigm if isinstance(cfg.paradigm, dict) else {}).get('traversal') or {}
    if isinstance(trav, dict):
        return str(trav.get('traverser_alternation', 'alternate'))
    return str(getattr(trav, 'traverser_alternation', 'alternate'))


def cfr_spec_sampler(cfg: Any, actor_id: int) -> EpisodeSpec:
    """One traversal spec, D1.B field-reuse encode (decode = CFRTraversalRunner.run):
    ``scenario_seed`` = env seed; ``starting_player`` REUSED for traverser_player
    via shared :func:`pick_traverser_player` (honors the SAME ``traverser_alternation``
    cfg as the serial collector — no silent divergence; unknown mode raises);
    ``opponent_id`` = ``'cfr_traverser'`` sentinel; ``epsilon`` REUSED as the
    ``float(seq)`` per-sample iteration tag (needs no cross-actor monotonicity —
    advantage nets functional, tag only labels reservoir samples)."""
    from training.paradigms.cfr._collect_helpers import pick_traverser_player

    seq = _SPEC_COUNTERS.get(actor_id, 0)
    _SPEC_COUNTERS[actor_id] = seq + 1
    pick_rng = random.Random(_derive_seed(int(cfg.meta.seed), 'cfr-pick', int(actor_id), int(seq)))
    return EpisodeSpec(
        scenario_seed=_derive_seed(int(cfg.meta.seed), 'cfr-actor', int(actor_id), 'traversal', int(seq)),
        opponent_id=OPP_SENTINEL,
        starting_player=pick_traverser_player(_read_traverser_alternation(cfg), seq, pick_rng),
        epsilon=float(seq),
    )


class _CFRTraversalPolicy:
    """Stub EpisodePolicy — exists only because actor_main requires a non-None
    policy. ``act`` raises so a wiring bug fails loud (CFR walks via traverser)."""

    def reset(self, *args: Any, **kwargs: Any) -> None:
        return None

    def act(self, *args: Any, **kwargs: Any):
        raise RuntimeError(
            '_CFRTraversalPolicy.act called — CFR walks via provider.traverser.traverse, '
            'not policy.act. Likely wired with EpisodeRunner not build_cfr_traversal_runner.'
        )


class CFRTraversalRunner:
    """AB14 lifecycle-runner — one tree traversal per ``run`` call (replaces
    ``EpisodeRunner``'s episode lifecycle). Single decode site for the D1.B
    EpisodeSpec field-reuse schema."""

    def __init__(self, env_factory, opp_registry) -> None:
        del opp_registry  # traversal has no opponent
        self.env_factory = env_factory

    def run(self, spec: EpisodeSpec, policy: Any, provider: Any) -> '_CFRRunnerOutput':
        del policy  # traversal doesn't step via policy.act
        from training.paradigms.cfr._collect_helpers import drain_single_traversal

        # Decode D1.B field-reuse (single decode site).
        iteration = int(spec.epsilon)
        traverser_p = int(spec.starting_player)
        # Clear per-traversal so drain_single_traversal sees exactly one game.
        for c in provider.adv_cols:
            c.clear()
        provider.strat_col.clear()
        provider.val_col.clear()

        env = self.env_factory(spec.scenario_seed)
        try:
            provider.traverser.traverse(env, traverser_player=traverser_p, iteration=iteration)
            batch = drain_single_traversal(provider.adv_cols, provider.strat_col, provider.val_col, traverser_p)
        finally:
            env.close()
        return _CFRRunnerOutput(transitions=[], cfr_batch=batch)


def build_cfr_traversal_runner(env_factory, opp_registry) -> CFRTraversalRunner:
    """AB14 ``episode_runner_factory`` target (dotted-path resolvable)."""
    return CFRTraversalRunner(env_factory, opp_registry)


class _CFRActorProvider:
    """Holds 2 AdvantageNets + CFRTraverser + per-traversal collectors.
    ``CFRTraversalRunner`` reads ``traverser`` / ``adv_cols`` / ``strat_col`` /
    ``val_col``. ``update_weights`` (called arg-less by actor_main between
    traversals) polls both SHM slots, reloading the matching net on a version
    bump (D2=A poll-based, D3=C no barrier)."""

    def __init__(self, nets, traverser, shm, adv_cols, strat_col, val_col, versions) -> None:
        self._nets = list(nets)
        self.traverser = traverser
        self._shm = shm
        self.adv_cols = adv_cols
        self.strat_col = strat_col
        self.val_col = val_col
        self._versions = list(versions)

    def update_weights(self) -> int:
        for p in range(2):
            sd, ver = self._shm.read(f'cfr_adv_p{p}')
            if sd is not None and int(ver) > self._versions[p]:
                self._nets[p].load_state_dict(sd)
                self._nets[p].eval()
                self._versions[p] = int(ver)
        return self.current_version()

    def current_version(self) -> int:
        return min(self._versions)

    def close(self) -> None:
        try:
            self._shm.close()
        except Exception:
            pass


@dataclass
class _CFRRunnerOutput:
    """Picklable runner output for IPC transport. ``transitions`` is the empty
    EpisodeRunner-contract surface; CFR sets ``push_episode_record=True`` so the
    FULL object is pushed and the collector reads ``cfr_batch``."""

    cfr_batch: Any
    transitions: list = field(default_factory=list)
