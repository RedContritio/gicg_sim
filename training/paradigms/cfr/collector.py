"""CFRTraversalCollector — wraps OS-MCCFR traversal as a core.Collector.

Spec ref: paradigm-cfr/spec.md C5. Unlike episode-rollout paradigms
(AZ / DMC / PPO), CFR collection runs **game-tree traversal** —
``CFRTraverser.traverse`` walks the tree per `traverser_player`,
pushing advantage / strategy / value samples directly into central
buffers (advantage[0/1] + strategy + value, per C3.1).

This adapter:
  - Owns one ``CFRTraverser`` instance (P3-B serial; P5 will move the
    multi-process worker path of ``training.paradigms.cfr.worker`` into
    ``core.actor.runtime``).
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
but ignored; the traverser holds direct references to the nets. P5
mp-mode will route forward through `provider` instead.

An ``CFRAsyncCollector`` placeholder lives at the bottom of this
module — async mp wiring is **architecturally non-trivial** for CFR
(traversal vs episode-rollout mismatch with ``core/actor/runtime`` —
see class docstring) and CFR is frozen-research tier (C6.1), so the
ship is NotImplementedError until an OpenSpec change unfreezes a real
async CFR path.
"""

from __future__ import annotations

import random
from typing import Any

from training.paradigms.cfr._collect_helpers import (
    CollectorBuffer,
    drain_single_traversal,
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
            max_tokens_per_hook=agent_cfg.max_tokens_per_hook,
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
        mode = self.pcfg.traversal.traverser_alternation
        if mode == 'alternate':
            return k % 2
        if mode == 'random':
            return self.rng.randint(0, 1)
        raise ValueError(f'CFRTraversalCollector: unknown traverser_alternation {mode!r}')

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


class CFRAsyncCollector:
    """Async (multi-worker) CFR collector — **architecturally deferred**.

    Why NotImplementedError rather than wrap ``legacy/parallel_trainer``:

    1. **Paradigm-architectural mismatch**. ``training.core.actor.runtime``
       (W3a, ddfb18a) spawns N ``ActorProcess`` workers running
       ``EpisodeRunner``-driven env rollouts (step -> obs -> action ->
       reward). OS-MCCFR traversal is **game-tree walking**, not env
       stepping — the worker descends the tree, samples one action per
       infoset via regret-matching, recurses, backs up counterfactual
       values. There is no episode, no reward signal at the
       step level, no per-step transition payload. ``ActorRuntime``
       cannot host CFR traversal without a parallel non-episode worker
       abstraction.

    2. **legacy/parallel_trainer is a trainer, not a collector**.
       ``ParallelCFRTrainer`` subclasses ``CFRTrainer`` and owns the
       complete train loop (traversals + fit_advantage + fit_strategy +
       weight broadcast). Wrapping it in a ``CollectorOutput`` interface
       would make the driver's ``train_step`` a no-op (training already
       happened inside the wrapped trainer), violating the
       collector/learner separation the unified pipeline depends on.
       A faithful async CFR collector requires rewriting traversal
       workers as pure samplers (push samples back to driver-owned
       reservoirs + fit), which is a larger refactor than the
       frozen-research tier justifies.

    3. **Frozen-research tier** (spec C6.1 / memory
       ``project_rl_routes_closure_2026_05_12``). New CFR runs SHALL
       NOT launch without OpenSpec change unfreezing (C6.3). The
       implementer of that change is the right person to choose
       between: (a) full rewrite of legacy/worker as collector-only
       samplers + driver-side fit, (b) add a non-episode worker
       primitive to ``core.actor`` (TraversalRunner), or (c) keep
       legacy/parallel_trainer untouched and bypass the unified driver
       for CFR runs entirely.

    For now: serial mode (``CFRTraversalCollector``) is the only
    supported CFR path under the unified driver. Async mp users should
    invoke ``training.paradigms.cfr.parallel_trainer`` directly.

    Matches the placeholder pattern used by ``AZAsyncCollector`` and
    ``DMCMultiProcessCollector`` — same intent (defer async wiring
    until a real implementer commits), different rationale (CFR's
    deferral is architectural, not just engineering scope).
    """

    requires_network_in_collect = True

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError(
            'CFRAsyncCollector: async multi-worker mode not wired into the '
            'unified driver. CFR traversal is game-tree walking, not env '
            'episode rollout — ActorRuntime (core/actor/runtime.py, W3a) is '
            'episode-runner-based and cannot host traversal workers without '
            'a separate TraversalRunner primitive. CFR is frozen-research '
            'tier (paradigm-cfr/spec.md C6.1); for async traversal use '
            'training.paradigms.cfr.parallel_trainer directly (bypasses the '
            'unified driver). See CFRAsyncCollector docstring for the full '
            'three-option resolution path.'
        )
