"""CFRTraversalCollector — wraps OS-MCCFR traversal as a core.Collector.

Spec ref: paradigm-cfr/spec.md C5. Unlike episode-rollout paradigms
(AZ / DMC / PPO), CFR collection runs **game-tree traversal** —
``CFRTraverser.traverse`` walks the tree per `traverser_player`,
pushing advantage / strategy / value samples directly into central
buffers (advantage[0/1] + strategy + value, per C3.1).

This adapter:
  - Owns one ``CFRTraverser`` instance (serial path). The async mp path
    now lives in ``training.paradigms.cfr._async.CFRAsyncCollector``,
    which drives N actors through the shared ``core/actor`` runtime
    (I31 #88 CFR mp-pool unification).
  - For each ``collect(n_traversals, provider)`` call: runs
    ``n_traversals`` traversals, alternating ``traverser_player``
    according to ``traversal.traverser_alternation``.
  - Produces a ``CollectorOutput`` whose ``runtime_metrics`` carries the
    drained sample batches; the (CFR-specific) ``CFRReservoirBuffer``
    consumes them in ``Buffer.push``.

``requires_network_in_collect = True`` per C5.2 (advantage net forward
samples regret-matching action distribution during traversal).

NOTE on `provider`: in serial mode the AdvantageNets live in the same
process as the collector — `provider` is accepted for protocol shape
but ignored; the traverser holds direct references to the nets. The
async mp path (``training.paradigms.cfr._async.CFRAsyncCollector``)
routes forward through per-actor providers instead.
"""

from __future__ import annotations

import random
from typing import Any

from training.paradigms.cfr._collect_helpers import (
    CollectorBuffer,
    drain_single_traversal,
    pick_traverser_player,
)
from training.paradigms.cfr.traversal import CFRTraverser, TraversalConfig
from training.core.protocols import CollectorOutput


class CFRTraversalCollector:
    """OS-MCCFR traversal collector. One call → N traversals → samples
    bundled into ``CollectorOutput.runtime_metrics['cfr_batches']``."""

    requires_network_in_collect = True

    def __init__(
        self,
        cfg: Any,
        paradigm_cfg: Any,
        network: Any,
        env_factory: Any,
    ) -> None:
        """Args:
        cfg: TrainingConfig (reads cfg.meta.seed).
        paradigm_cfg: CFRParadigmConfig.
        network: CFRNetwork — exposes `advantage_nets[0/1]` (used by
            traverser for regret-matching action sampling) +
            `strategy_net` (used by traversal's value bootstrap when
            enabled).
        env_factory: callable(seed) -> GicgEnv. Same shape as DMC.
        """
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self.env_factory = env_factory
        self._master_seed = int(cfg.meta.seed)
        self.rng = random.Random(self._master_seed + 7)
        self._iteration = 0  # traversal-iter counter (advances per collect)
        self._traversal_seq = 0

        # Per-traversal collectors (drained each traversal).
        self._adv_cols = [CollectorBuffer(), CollectorBuffer()]
        self._strat_col = CollectorBuffer()
        self._val_col = CollectorBuffer()

        trav_cfg = TraversalConfig(
            sampling_mode=paradigm_cfg.traversal.sampling_mode,
            epsilon=paradigm_cfg.traversal.epsilon,
            max_game_steps=paradigm_cfg.traversal.max_game_steps,
            importance_weight_max=paradigm_cfg.traversal.importance_weight_max,
        )
        self._traversal_cfg = trav_cfg

        # Build traverser. CFRTraverser ctor expects:
        # advantage_nets / *_buffers / counter/hook shapes / config / rng / device.
        agent_cfg = paradigm_cfg.agent
        self.traverser = CFRTraverser(
            advantage_nets=[network.advantage_head(0), network.advantage_head(1)],
            n_counter_slots=agent_cfg.n_counter_slots,
            max_ops_per_hook=agent_cfg.max_ops_per_hook,
            n_hooks_capacity=agent_cfg.n_hooks,
            max_actions=agent_cfg.max_actions,
            advantage_buffers=self._adv_cols,  # type: ignore[arg-type]
            strategy_buffer=self._strat_col,  # type: ignore[arg-type]
            value_buffer=self._val_col,  # type: ignore[arg-type]
            config=trav_cfg,
            rng=self.rng,
            device=network.device,
        )

    def _pick_traverser(self, k: int) -> int:
        return pick_traverser_player(self.pcfg.traversal.traverser_alternation, k, self.rng)

    def collect(self, n_units: int, provider: Any) -> CollectorOutput:
        """Run ``n_units`` OS-MCCFR traversals.

        Args:
            n_units: number of traversals (NOT episodes — spec C5.1).
            provider: ignored in serial mode (see module docstring).
        Returns:
            CollectorOutput with the drained per-traversal sample batches
            in ``runtime_metrics['cfr_batches']`` for buffer ingestion.
        """
        del provider  # serial mode: advantage_nets shared in-process
        # Eval mode for traverser-side advantage forwards (regret-match
        # action sampling) — mirrors `CFRTrainer._run_traversals` shape.
        for p in range(2):
            self.network.advantage_head(p).eval()

        batches: list = []
        traversal_stats: list = []
        n_samples_total = 0
        for k in range(max(1, n_units)):
            self._traversal_seq += 1
            seed = 1_000_000 * self._iteration + k
            env = self.env_factory(seed)
            try:
                tp = self._pick_traverser(k)
                self.traverser.traverse(
                    env,
                    traverser_player=tp,
                    iteration=self._iteration,
                )
                batch = drain_single_traversal(
                    self._adv_cols,
                    self._strat_col,
                    self._val_col,
                    traverser_player=tp,
                )
                batches.append(batch)
                n_adv0, n_adv1, n_strat, n_val = batch.n_samples()
                n_samples_total += n_adv0 + n_adv1 + n_strat + n_val
                traversal_stats.append(
                    {
                        'traversal_idx': self._traversal_seq,
                        'iteration': self._iteration,
                        'traverser_player': int(tp),
                        'n_adv': int(n_adv0 + n_adv1),
                        'n_strat': int(n_strat),
                        'n_val': int(n_val),
                    }
                )
            finally:
                if hasattr(env, 'close'):
                    try:
                        env.close()
                    except Exception:
                        pass

        self._iteration += 1

        return CollectorOutput(
            transitions=[],  # CFR uses cfr_batches in runtime_metrics
            episode_stats=traversal_stats,
            runtime_metrics={
                'cfr_batches': batches,
                'cfr_iteration': self._iteration,
            },
            n_units=n_samples_total,
        )

    def close(self) -> None:
        return None

    def state_dict(self) -> dict:
        return {
            'iteration': self._iteration,
            'traversal_seq': self._traversal_seq,
            'master_seed': self._master_seed,
            'rng_state': self.rng.getstate(),
        }

    def load_state_dict(self, sd: dict) -> None:
        self._iteration = int(sd.get('iteration', 0))
        self._traversal_seq = int(sd.get('traversal_seq', 0))
        self._master_seed = int(sd.get('master_seed', self._master_seed))
        if 'rng_state' in sd:
            self.rng.setstate(sd['rng_state'])
