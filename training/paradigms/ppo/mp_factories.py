"""PPO mp-mode factories — env, opp registry, policy, provider + spec sampler.

Wired into spawned actors via ``PPOAsyncCollector.__init__`` (sibling
module ``_async.py``):parent constructs ``WeightsSHM.serialize_for_worker``
+ pickles network blueprint to tempfile, threads both via per-actor
``provider_kwargs={'weights_shm_info': ..., 'network_blueprint_path': ...}``
into ``actor_main`` (paradigm-agnostic AB13 escape hatch).

**DMC template alignment** (2026-05-29 / I31 backlog #88):

This module follows the DMC ``training.paradigms.dmc.mp_factories`` pattern
— factories are top-level + spawn-safe, ``actor_main`` resolves them via
dotted-path strings in the child, parent owns the spawn-safe handoff via
``actor_kwargs_factory``. The PPO escape hatch is ``provider_kwargs`` (vs
DMC ``inference_client``) per AB13.

**cfg-driven, no env var** (post 2026-05-23 ``feedback_cfg_driven_only``):
``build_opp_registry`` + ``spec_sampler`` read
``cfg.paradigm['rollout']['rollout_opponent']`` directly. ``cfg`` is
auto-pickled by mp spawn ctx into the child, so child reads the same
``opp_id`` parent configured — no env var bridge.

**Frozen tier** (per ADR-0008 / ``paradigm.py:16``): PPO async path is
maintenance-only; ``_PPOActorProvider`` wraps ``LocalNetworkProvider`` +
``WeightsSHM`` for simple weight broadcast, no ``InferenceServer``
integration (DMC's batched-forward route is overkill for the frozen
tier's reproducibility-only acceptance).
"""

from __future__ import annotations

import pickle
import random
from typing import Any

from training.core.protocols import EpisodeSpec


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

    from training.core.scenario import decks_arg

    scen = cfg.scenario
    fd = list(scen.fix_dice) if getattr(scen, 'fix_dice', None) else None
    decks = decks_arg(getattr(scen, 'deck_0', None), getattr(scen, 'deck_1', None))

    def _factory(scenario_seed: int):
        env = GicgEnv(
            list(scen.team_0),
            list(scen.team_1),
            card_pool=getattr(scen, 'card_pool', None),
            seed=int(scenario_seed),
            data_dir=str(getattr(scen, 'data_dir', 'data')),
            max_rounds=int(getattr(scen, 'max_rounds', 3)),
            fix_dice=fd,
            deck_padding=getattr(scen, 'deck_padding', None),
            pool=getattr(scen, 'pool', ['v_legacy', 'test_basic']),
            decks=decks,
        )
        env.reset(seed=int(scenario_seed))
        return env

    return _factory


def _read_rollout_opponent(cfg: Any) -> str:
    """Read ``cfg.paradigm['rollout']['rollout_opponent']`` (dict form post mp
    spawn). Default to ``'random'`` if missing — matches pre-cleanup env-var
    fallback (``os.environ.get(_ENV_OPPONENT, 'random')``)."""
    pdict = cfg.paradigm if isinstance(cfg.paradigm, dict) else {}
    rollout = pdict.get('rollout') or {}
    if isinstance(rollout, dict):
        return str(rollout.get('rollout_opponent', 'random'))
    # Defensive: rollout may be a dataclass instance in some test paths.
    return str(getattr(rollout, 'rollout_opponent', 'random'))


def build_opp_registry(cfg: Any):
    """Frozen tier opp registry — only接 random baseline. Full F1-D2 mix lives
    in legacy ``_rollout.make_rollout_opponent`` (serial path)."""
    from training.core.eval.baselines import OpponentRegistry

    def _mk(seed, params):
        del params
        rng = random.Random(int(seed))

        class _R:
            def select_action(self, env):
                kinds, _ = env.get_legal_actions() if hasattr(env, 'get_legal_actions') else ([0], None)
                return rng.choice(list(kinds)) if kinds else 0

        return _R()

    reg = OpponentRegistry()
    extra = _read_rollout_opponent(cfg)
    for tag in {'rollout', 'random', 'self', extra}:
        reg.register(tag, _mk)
    return reg


def build_policy(cfg: Any, actor_id: int):
    from training.paradigms.ppo.policy import PPOEpisodePolicy

    pcfg = dict(cfg.paradigm) if hasattr(cfg, 'paradigm') else {}
    return PPOEpisodePolicy(
        gamma=float(pcfg.get('gamma', 0.99)),
        gae_lambda=float(pcfg.get('gae_lambda', 0.95)),
        seed=int(cfg.meta.seed) + 1000 + int(actor_id),
        deterministic=False,
    )


def build_provider(cfg: Any, actor_id: int, *, weights_shm_info: dict, network_blueprint_path: str):
    """Per-actor provider — WeightsSHM.attach + LocalNetworkProvider wrap.

    Required spawn-safe kwargs (parent → child via ``actor_kwargs_factory``
    → ``provider_kwargs`` per AB13):

    - ``weights_shm_info``: dict returned by
      ``WeightsSHM.serialize_for_worker(['latest'])`` (parent side); child
      re-attaches via ``WeightsSHM.attach(info)``。
    - ``network_blueprint_path``: tempfile path str to a pickled cpu network
      blueprint (parent owned the file); child loads via ``pickle.load``。

    Raises RuntimeError if WeightsSHM 'latest' slot cold (parent must
    publish before spawn)."""
    del cfg, actor_id
    from training.core.actor.network_provider import LocalNetworkProvider
    from training.core.actor.weights_shm import WeightsSHM

    with open(network_blueprint_path, 'rb') as f:
        network = pickle.load(f)
    shm = WeightsSHM.attach(weights_shm_info)
    sd, version = shm.read('latest')
    if sd is None:
        raise RuntimeError('PPOAsync: WeightsSHM latest cold — publish before spawn')
    network.load_state_dict(sd)
    network.eval()
    local = LocalNetworkProvider(network, device='cpu', version_tag='latest')
    local.version = int(version)
    return _PPOActorProvider(local, shm)


_SPEC_COUNTERS: dict = {}


def spec_sampler(cfg: Any, actor_id: int) -> EpisodeSpec:
    """Sample one EpisodeSpec per call. Per-actor counter monotonic; opp_id
    read from cfg (not env var). ``'self'`` → ``'random'`` retreat (frozen
    tier does not host self-play infra)."""
    seq = _SPEC_COUNTERS.get(actor_id, 0)
    _SPEC_COUNTERS[actor_id] = seq + 1
    seed = _derive_seed(int(cfg.meta.seed), 'actor', int(actor_id), 'episode', int(seq))
    opp = _read_rollout_opponent(cfg)
    return EpisodeSpec(scenario_seed=int(seed), opponent_id='random' if opp == 'self' else opp)


class _PPOActorProvider:
    """LocalNetworkProvider + WeightsSHM:update_weights polls SHM 'latest'."""

    def __init__(self, local_provider, shm) -> None:
        self._local = local_provider
        self._shm = shm

    def forward(self, obs: Any, mask: Any) -> Any:
        return self._local.forward(obs, mask)

    def update_weights(self, version_tag: str = 'latest', state_dict: dict = None) -> int:
        if state_dict is not None:
            return self._local.update_weights(state_dict=state_dict)
        sd, ver = self._shm.read(version_tag)
        if sd is not None and ver > self._local.current_version():
            self._local.replace_weights(sd, int(ver))
        return self._local.current_version()

    def current_version(self) -> int:
        return self._local.current_version()

    def close(self) -> None:
        self._local.close()
