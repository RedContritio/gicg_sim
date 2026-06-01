"""AZ collectors — serial selfplay + (I31 #88 AZ) multi-process.

Serial: :class:`AZSelfPlayCollector` wraps ``play_self_game`` (one game per
``collect``, both sides share the SAME in-process network — A5.2).

Async: :class:`AZAsyncCollector` lives in :mod:`training.paradigms.az._async`
(split out to stay under the 300-line cap, mirroring
``training.paradigms.cfr._async``) and is re-exported here for the existing
``paradigm.py`` / test imports. It runs N actor processes through the shared
``core/actor`` runtime + a centralized :class:`InferenceServer`.
"""

from __future__ import annotations

import random
from typing import Any

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


# AZ multi-process collector (I31 #88 AZ) — implementation in _async.py
# (300-line cap split, mirror cfr/_async.py). Re-exported for paradigm.py + tests.
from training.paradigms.az._async import AZAsyncCollector  # noqa: E402,F401
