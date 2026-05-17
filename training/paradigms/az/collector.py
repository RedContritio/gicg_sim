"""AZ collectors — serial selfplay + (FU-W3b-AZ) multi-process.

Serial: wraps ``play_self_game`` (one game per ``collect``). Async:
:class:`AZAsyncCollector` wires real mp via :class:`Runtime` (WeightsSHM
+ ActorProcess pool + SHMRing). End-to-end still needs AZ migration off
``play_self_game`` onto typed ``EpisodePolicy``; this task contracts the
API surface only, mirroring DMCAsyncCollector pattern.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from training.core.actor.ipc.ring import SHMRing
from training.core.actor.runtime import Runtime
from training.core.protocols import CollectorOutput
from training.paradigms.az.mcts import MCTSConfig
from training.paradigms.az.pool_spec import make_pool_spec, resolve_pool_refs
from training.paradigms.az.selfplay import play_self_game


def derive_seed(master_seed: int, *labels: Any) -> int:
    """Deterministic seed from master + labels. Same shape as DMC's
    derive_seed (intentional dup — paradigm isolation per ADR-0006)."""
    h = master_seed & 0xFFFFFFFF
    for lab in labels:
        s = repr(lab).encode('utf-8')
        for b in s:
            h = (h * 1000003) ^ b
            h &= 0xFFFFFFFF
    return int(h & 0x7FFFFFFF)


def _build_mcts_config(pcfg) -> MCTSConfig:
    """Translate ``AZParadigmConfig.mcts`` → legacy ``MCTSConfig``."""
    m = pcfg.mcts
    return MCTSConfig(
        n_rollouts=m.n_rollouts,
        c_puct=m.c_puct,
        dirichlet_alpha=m.dirichlet_alpha,
        dirichlet_eps=m.dirichlet_eps,
        temperature=m.temperature,
        temperature_switch_step=m.temperature_switch_step,
        max_rollout_depth=m.max_rollout_depth,
        parallel_rollouts=m.parallel_rollouts,
        value_mix_lambda=m.value_mix_lambda,
        prior_mix_lambda=m.prior_mix_lambda,
        lambda_anneal_games=m.lambda_anneal_games,
        lambda_start=m.lambda_start,
        lambda_end=m.lambda_end,
        profile=m.profile,
        backend=m.backend,
    )


class AZSelfPlayCollector:
    """Single-process selfplay collector (spec A5.1-A5.3). Both sides
    share the SAME ``network`` instance (A5.2)."""

    requires_network_in_collect = True

    def __init__(self, cfg: Any, paradigm_cfg: Any, network: Any, env: Any) -> None:
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self.env = env
        self._episode_seq = 0
        self._master_seed = int(cfg.meta.seed)
        self._rng_search = random.Random(derive_seed(self._master_seed, 'mcts-search'))
        self._mcts_cfg = _build_mcts_config(paradigm_cfg)
        self._card_pool_spec = make_pool_spec(cfg.scenario, resolve_pool_refs(cfg.scenario))  # A5.4

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        """Run ``n_episodes`` selfplay games serially. ``provider``
        ignored — eval is in-proc via the wrapped AZNetwork."""
        del provider  # serial mode: in-process eval
        trajectories: list = []
        episode_stats: list = []
        n_trans_total = 0
        for _ in range(max(1, n_episodes)):
            self._episode_seq += 1
            ep_seed = derive_seed(self._master_seed, 'episode', self._episode_seq)
            self.env.reset(seed=ep_seed)
            result = play_self_game(
                self.network,  # AZNetwork.eval_state matches MCTS contract
                self.env,
                self._card_pool_spec,
                self._rng_search,
                self._mcts_cfg,
                max_game_steps=self.pcfg.max_game_steps,
                n_counter_slots=self.pcfg.agent.n_counter_slots,
                max_actions=self.pcfg.agent.max_actions,
            )
            if result.steps:
                trajectories.append((result.game_static, result.steps))
                n_trans_total += result.n_steps
            episode_stats.append(
                {
                    'ep_idx': self._episode_seq,
                    'n_steps': int(result.n_steps),
                    'winner': int(result.winner),
                    'discovery_count': int(result.discovery_count),
                }
            )
        return CollectorOutput(
            transitions=[],
            episode_stats=episode_stats,
            runtime_metrics={'az_trajectories': trajectories},
            n_units=n_trans_total,
        )

    def close(self) -> None:
        if hasattr(self.env, 'close'):
            try:
                self.env.close()
            except Exception:
                pass

    def state_dict(self) -> dict:
        return {
            'episode_seq': self._episode_seq,
            'master_seed': self._master_seed,
            'rng_search': self._rng_search.getstate(),
        }

    def load_state_dict(self, sd: dict) -> None:
        self._episode_seq = sd.get('episode_seq', 0)
        self._master_seed = sd.get('master_seed', self._master_seed)
        if 'rng_search' in sd:
            self._rng_search.setstate(sd['rng_search'])


# ---------- AZ multi-process collector (FU-W3b-AZ) ---------- #

# Per-actor episode counter; children get their own copy after spawn.
_AZ_ACTOR_EP_SEQ: dict = {}


def _resolve_paradigm_factory(cfg: Any, key: str) -> Any:
    """Look up dotted ``module.attr`` in cfg.paradigm + import. CS4 strict."""
    from training.core.actor.actor_process import resolve_builder

    pdict = cfg.paradigm if isinstance(cfg.paradigm, dict) else {}
    path = pdict.get(key)
    if not path:
        raise ValueError(
            f'AZ mp actor: cfg.paradigm.{key} required for spawn (dotted "module.attr").',
        )
    return resolve_builder(path)


def _az_build_env_factory(cfg: Any, seed: int):
    return _resolve_paradigm_factory(cfg, 'mp_env_factory_path')(cfg, seed)


def _az_build_opp_registry(cfg: Any):
    """A5.2 self-play: paradigm cfg registers 'self' → same-network factory."""
    return _resolve_paradigm_factory(cfg, 'mp_opp_registry_path')(cfg)


def _az_build_policy(cfg: Any, actor_id: int):
    """AZEpisodePolicy with mcts_cfg + card_pool_spec. Generic
    ``actor_main`` calls ``policy.act(obs, mask, provider)``; obs must
    carry ``env`` for MCTS determinization (paradigm env_factory packs it)."""
    from training.paradigms.az.config import AZParadigmConfig
    from training.paradigms.az.policy import AZEpisodePolicy

    pcfg = AZParadigmConfig.from_dict(cfg.paradigm if isinstance(cfg.paradigm, dict) else {})
    return AZEpisodePolicy(
        mcts_cfg=_build_mcts_config(pcfg),
        card_pool_spec=make_pool_spec(cfg.scenario, resolve_pool_refs(cfg.scenario)),  # A5.4
        seed=int(cfg.meta.seed) + 17 + actor_id,
        deterministic=False,
        n_counter_slots=pcfg.agent.n_counter_slots,
        max_actions=pcfg.agent.max_actions,
    )


def _az_build_provider(cfg: Any, actor_id: int):
    return _resolve_paradigm_factory(cfg, 'mp_provider_path')(cfg, actor_id)


def _az_spec_sampler(cfg: Any, actor_id: int):
    from training.core.protocols import EpisodeSpec

    _AZ_ACTOR_EP_SEQ[actor_id] = _AZ_ACTOR_EP_SEQ.get(actor_id, 0) + 1
    seed = derive_seed(int(cfg.meta.seed), 'mp_ep', actor_id, _AZ_ACTOR_EP_SEQ[actor_id])
    # A5.2: opponent_id='self' — opp_registry must resolve to same network.
    return EpisodeSpec(scenario_seed=seed, opponent_id='self')


class AZAsyncCollector:
    """AZ async collector — N actor processes + SHM ring + WeightsSHM.

    Owns a :class:`Runtime` (ActorProcess pool + WeightsSHM). Mirrors
    DMCAsyncCollector pattern. End-to-end production still requires AZ
    migration off ``play_self_game`` onto typed EpisodePolicy.

    ``env_factory`` arg ignored — mp workers rebuild env via
    ``cfg.paradigm.mp_env_factory_path`` (closures unpicklable for spawn).
    """

    requires_network_in_collect = True

    def __init__(
        self,
        cfg: Any,
        paradigm_cfg: Any,
        network: Any,
        env_factory: Any = None,
        *,
        runtime: Optional[Runtime] = None,
        ring: Optional[SHMRing] = None,
    ) -> None:
        del env_factory  # workers rebuild env from cfg (closures unpicklable for spawn)
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self._master_seed = int(cfg.meta.seed)
        self._episode_seq = 0
        self._weights_version = 0
        self.runtime = runtime if runtime is not None else Runtime(cfg)
        self.ring = ring if ring is not None else SHMRing(capacity=1024, slot_payload_max=512 * 1024)
        self._spawned = False

    def _bootstrap(self) -> None:
        """One-shot publish-then-spawn (idempotent). W3a #2: publish before
        children attach so they see version=0+ on first read."""
        if self._spawned:
            return
        sd_cpu = {k: v.detach().cpu() for k, v in self.network.state_dict().items()}
        self.runtime.publish_weights(sd_cpu, version=self._weights_version)
        prefix = 'training.paradigms.az.collector'
        actor_kwargs = {
            'build_env_factory_path': f'{prefix}._az_build_env_factory',
            'build_opp_registry_path': f'{prefix}._az_build_opp_registry',
            'build_policy_path': f'{prefix}._az_build_policy',
            'build_provider_path': f'{prefix}._az_build_provider',
            'spec_sampler_path': f'{prefix}._az_spec_sampler',
            'transition_queue': self.ring,
        }
        n_actors = int(getattr(self.cfg.pipeline, 'num_actors', 1))
        self.runtime.start_actors(n_actors=n_actors, actor_kwargs_factory=lambda i: dict(actor_kwargs))
        self._spawned = True

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        """Drain SHM ring → CollectorOutput. ``n_episodes`` caps pulls per iter."""
        del provider  # actors own their own providers
        self._bootstrap()
        trajectories: list = []
        episode_stats: list = []
        n_trans_total = 0
        n_pulled = 0
        max_pull = max(1, int(n_episodes))
        while n_pulled < max_pull:
            item = self.ring.try_pop()
            if item is None:
                break
            self._episode_seq += 1
            n_trans = len(item) if hasattr(item, '__len__') else 0
            # (game_static, steps) tuple — game_static=None until AZ migrates
            # off play_self_game onto typed EpisodePolicy + EpisodeRunner.
            trajectories.append((None, item))
            n_trans_total += n_trans
            episode_stats.append({'ep_idx': self._episode_seq, 'n_transitions': n_trans, 'source': 'mp_actor'})
            n_pulled += 1
        return CollectorOutput(
            transitions=[],
            episode_stats=episode_stats,
            runtime_metrics={'az_trajectories': trajectories, 'n_pulled': n_pulled},
            n_units=n_trans_total,
        )

    def sync_weights(self, network: Any) -> int:
        """Publish latest weights to WeightsSHM. Actors poll between episodes."""
        self._weights_version += 1
        sd_cpu = {k: v.detach().cpu() for k, v in network.state_dict().items()}
        self.runtime.publish_weights(sd_cpu, version=self._weights_version)
        return self._weights_version

    def close(self) -> None:
        for r in (self.runtime, self.ring):
            try:
                r.close()
            except Exception:
                pass
        self._spawned = False

    def state_dict(self) -> dict:
        return {
            'episode_seq': self._episode_seq,
            'master_seed': self._master_seed,
            'weights_version': self._weights_version,
        }

    def load_state_dict(self, sd: dict) -> None:
        self._episode_seq = sd.get('episode_seq', 0)
        self._master_seed = sd.get('master_seed', self._master_seed)
        self._weights_version = sd.get('weights_version', 0)
