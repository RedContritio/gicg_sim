"""AZ collectors — serial selfplay + (I31 #88 AZ) multi-process.

Serial: :class:`AZSelfPlayCollector` wraps ``play_self_game`` (one game per
``collect``, both sides share the SAME in-process network — A5.2) or, when
``paradigm.fixed_opponent`` is set (ExIt 固定对手支线), the non-mirror
``play_vs_opponent_game`` against a pool player sampled per episode.

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
from training.paradigms.az.selfplay import play_self_game, play_vs_opponent_game


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
    share the SAME ``network`` instance (A5.2) — unless ``opponent_pool``
    is given (ExIt 固定对手支线): then the agent seat runs MCTS against
    a fixed pool player sampled per episode (non-mirror)."""

    requires_network_in_collect = True

    def __init__(
        self,
        cfg: Any,
        paradigm_cfg: Any,
        network: Any,
        env: Any,
        opponent_pool: Any = None,
    ) -> None:
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self.env = env
        self._opponent_pool = opponent_pool
        self._episode_seq = 0
        self._master_seed = int(cfg.meta.seed)
        self._rng_search = random.Random(derive_seed(self._master_seed, 'mcts-search'))
        self._mcts_cfg = _build_mcts_config(paradigm_cfg)
        self._card_pool_spec = make_pool_spec(cfg.scenario, resolve_pool_refs(cfg.scenario))  # A5.4
        # Batched-inference path (serial ExIt throughput): when the MCTS
        # cfg asks for parallel rollouts, evals route through a local
        # InferenceServer (separate process, batched forward) instead of
        # the in-process network — selfplay._mcts_decide then picks
        # mcts_search_parallel. parallel_rollouts == 1 (default) keeps
        # the legacy in-proc evaluator, byte-identical behavior.
        self._inference_server = None
        self._inference_client = None
        self._weights_version = 0
        if self._mcts_cfg.parallel_rollouts > 1:
            self._bootstrap_inference()

    def _bootstrap_inference(self) -> None:
        """Stand up the local InferenceServer + single worker client.

        Mirrors AZAsyncCollector._bootstrap's server construction (D3=C:
        weights live server-side; the server rebuilds an Agent from the
        same AgentConfig the collector's network was built from). The
        live training weights MUST be pushed before any eval — the
        server process starts from a random net."""
        from training.core.inference.client import InferenceClient
        from training.core.inference.server import InferenceServer
        from training.core.network import AgentConfig

        server = InferenceServer(
            agent_config=AgentConfig.from_obs_shape(self.pcfg.agent),
            n_workers=1,
            server_cfg=getattr(self.cfg, 'inference', None),
            network_factory_path='training.paradigms.az.network.Agent',
            inference_handlers_module_path='training.paradigms.az._inference_handlers',
        )
        server.start()
        server.push_weights(_cpu_net_state_dict(self.network))
        self._inference_server = server
        self._inference_client = InferenceClient(worker_id=0, pipe=server.get_worker_pipe(0))

    def sync_weights(self, network: Any) -> int:
        """Push current learner weights to the InferenceServer. Called by
        the pipeline's _maybe_sync_weights when the paradigm flips
        StepPlan.sync_weights (serial + parallel_rollouts > 1). No-op
        without a server (legacy in-proc paths)."""
        self._weights_version += 1
        if self._inference_server is not None:
            # Loud failure beats a silent wedge: if the server process died
            # (e.g. GPU context fault), weight_queue.put would block forever
            # once OS buffers fill.
            self._inference_server.check_alive()
            self._inference_server.push_weights(_cpu_net_state_dict(network))
        return self._weights_version

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        """Run ``n_episodes`` selfplay games serially. ``provider``
        ignored — eval is in-proc (or via the local InferenceServer when
        parallel_rollouts > 1)."""
        del provider  # serial mode: collector owns its eval path
        evaluator = self._inference_client if self._inference_client is not None else self.network
        trajectories: list = []
        episode_stats: list = []
        n_trans_total = 0
        for _ in range(max(1, n_episodes)):
            self._episode_seq += 1
            ep_seed = derive_seed(self._master_seed, 'episode', self._episode_seq)
            self.env.reset(seed=ep_seed)
            if self._opponent_pool is not None:
                opponent = self._opponent_pool.sample()
                result = play_vs_opponent_game(
                    evaluator,  # InferenceClient satisfies the evaluator protocol
                    self.env,
                    self._card_pool_spec,
                    self._rng_search,
                    self._mcts_cfg,
                    opponent,
                    max_game_steps=self.pcfg.max_game_steps,
                    n_counter_slots=self.pcfg.agent.n_counter_slots,
                    max_actions=self.pcfg.agent.max_actions,
                    agent_player=(self._episode_seq - 1) % 2,
                )
            else:
                result = play_self_game(
                    evaluator,  # InferenceClient satisfies the evaluator protocol
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
                    'agent_player': result.agent_player,
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
        if self._inference_server is not None:
            try:
                self._inference_server.stop()
            except Exception:
                pass
            self._inference_server = None
            self._inference_client = None
        if hasattr(self.env, 'close'):
            try:
                self.env.close()
            except Exception:
                pass

    def state_dict(self) -> dict:
        sd = {
            'episode_seq': self._episode_seq,
            'master_seed': self._master_seed,
            'rng_search': self._rng_search.getstate(),
            'weights_version': self._weights_version,
        }
        if self._opponent_pool is not None and hasattr(self._opponent_pool, 'state_dict'):
            sd['opponent_pool'] = self._opponent_pool.state_dict()
        return sd

    def load_state_dict(self, sd: dict) -> None:
        self._episode_seq = sd.get('episode_seq', 0)
        self._master_seed = sd.get('master_seed', self._master_seed)
        self._weights_version = sd.get('weights_version', 0)
        if 'rng_search' in sd:
            self._rng_search.setstate(sd['rng_search'])
        if 'opponent_pool' in sd and self._opponent_pool is not None:
            self._opponent_pool.load_state_dict(sd['opponent_pool'])


# AZ multi-process collector (I31 #88 AZ) — implementation in _async.py
# (300-line cap split, mirror cfr/_async.py). Re-exported for paradigm.py + tests.
from training.paradigms.az._async import AZAsyncCollector, _cpu_net_state_dict  # noqa: E402,F401
