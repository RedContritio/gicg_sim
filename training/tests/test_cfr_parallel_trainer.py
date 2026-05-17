"""Tests for training/paradigms/cfr/legacy/parallel_trainer.py — spawns real workers."""

from __future__ import annotations

import os

import numpy as np
import pytest

from training.paradigms.cfr import CFRNetConfig
from training.paradigms.cfr.parallel_trainer import ParallelCFRTrainer
from training.paradigms.cfr.train import CFRTrainConfig
from training.paradigms.cfr.traversal import TraversalConfig
from training.paradigms.cfr.worker import WorkerConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
N_HOOKS_CAP = 900
MAX_TOK = 120
MAX_ACTIONS = 2048


def _net_cfg() -> CFRNetConfig:
    return CFRNetConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=N_HOOKS_CAP,
        max_tokens_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )


def _train_cfg(**overrides) -> CFRTrainConfig:
    cfg = CFRTrainConfig(
        n_iterations=1,
        traversals_per_iteration=4,
        advantage_fit_steps_per_iter=2,
        strategy_fit_steps=2,
        strategy_fit_every=1,
        fit_batch_size=4,
        advantage_buffer_capacity=128,
        strategy_buffer_capacity=128,
        value_buffer_capacity=128,
        checkpoint_every=0,
        traversal=TraversalConfig(max_game_steps=400, epsilon=0.2),
        seed=0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _worker_cfg(net_cfg: CFRNetConfig) -> WorkerConfig:
    return WorkerConfig(
        net_cfg=net_cfg,
        team_0=['赤蝶'],
        team_1=['墨客'],
        card_pool=None,
        data_dir=DATA_DIR,
        traversal=TraversalConfig(max_game_steps=400, epsilon=0.2),
    )


class TestParallelTrainer:
    def test_two_workers_one_iteration(self):
        net_cfg = _net_cfg()
        with ParallelCFRTrainer(
            net_cfg=net_cfg,
            train_cfg=_train_cfg(traversals_per_iteration=4),
            worker_cfg=_worker_cfg(net_cfg),
            n_workers=2,
            worker_timeout_s=300.0,
        ) as trainer:
            m = trainer.run_iteration(0)
            assert m.n_traversals == 4
            # Each of 4 traversals contributes to value buffer; adv +
            # strat depend on traverser decisions per game (always > 0
            # unless game trivially terminates — smoke games don't)
            assert m.buffer_sizes['value'] > 0
            # Alternating traverser + 4 traversals → both sides' adv
            # buffers receive samples.
            assert m.buffer_sizes['advantage_p0'] > 0
            assert m.buffer_sizes['advantage_p1'] > 0
            assert m.buffer_sizes['strategy'] > 0
            assert np.isfinite(m.advantage_loss)

    def test_two_iterations_with_strategy_fit(self):
        net_cfg = _net_cfg()
        with ParallelCFRTrainer(
            net_cfg=net_cfg,
            train_cfg=_train_cfg(
                n_iterations=2,
                traversals_per_iteration=2,
            ),
            worker_cfg=_worker_cfg(net_cfg),
            n_workers=2,
            worker_timeout_s=300.0,
        ) as trainer:
            metrics = trainer.train()
            assert len(metrics) == 2
            # iter 1 runs strategy fit (iteration > 0 guard)
            assert metrics[1].strategy_loss is not None
            assert np.isfinite(metrics[1].strategy_loss)

    def test_work_distribution_uneven(self):
        """3 workers × 5 traversals → one worker gets 1, two get 2."""
        net_cfg = _net_cfg()
        with ParallelCFRTrainer(
            net_cfg=net_cfg,
            train_cfg=_train_cfg(traversals_per_iteration=5),
            worker_cfg=_worker_cfg(net_cfg),
            n_workers=3,
            worker_timeout_s=300.0,
        ) as trainer:
            m = trainer.run_iteration(0)
            assert m.n_traversals == 5
            # Total value samples = sum over 5 traversals; must match
            # the 5-traversal contribution
            assert m.buffer_sizes['value'] > 0

    def test_zero_workers_raises(self):
        net_cfg = _net_cfg()
        with pytest.raises(ValueError, match='n_workers'):
            ParallelCFRTrainer(
                net_cfg=net_cfg,
                train_cfg=_train_cfg(),
                worker_cfg=_worker_cfg(net_cfg),
                n_workers=0,
            )

    def test_shutdown_idempotent_and_kills_workers(self):
        """First shutdown must actually terminate workers. Second
        shutdown is a no-op."""
        net_cfg = _net_cfg()
        trainer = ParallelCFRTrainer(
            net_cfg=net_cfg,
            train_cfg=_train_cfg(),
            worker_cfg=_worker_cfg(net_cfg),
            n_workers=2,
        )
        procs = list(trainer._procs)
        trainer.shutdown()
        for p in procs:
            assert not p.is_alive(), f'worker {p.name} still alive after shutdown'
        trainer.shutdown()  # no crash on second call

    def test_mismatched_traversal_config_raises(self):
        """Worker and train configs must agree on traversal fields."""
        net_cfg = _net_cfg()
        train_cfg = _train_cfg()
        bad_worker = _worker_cfg(net_cfg)
        bad_worker.traversal = TraversalConfig(
            max_game_steps=400,
            epsilon=train_cfg.traversal.epsilon + 0.1,
        )
        with pytest.raises(ValueError, match='traversal'):
            ParallelCFRTrainer(
                net_cfg=net_cfg,
                train_cfg=train_cfg,
                worker_cfg=bad_worker,
                n_workers=1,
            )

    def test_worker_crash_surfaces_as_runtime_error(self):
        """Kill a worker process externally before dispatch. The next
        _run_traversals must raise RuntimeError with the worker id,
        not hang waiting for a response."""
        net_cfg = _net_cfg()
        with ParallelCFRTrainer(
            net_cfg=net_cfg,
            train_cfg=_train_cfg(traversals_per_iteration=2),
            worker_cfg=_worker_cfg(net_cfg),
            n_workers=2,
            worker_timeout_s=10.0,
        ) as trainer:
            # Kill one worker before dispatching
            trainer._procs[0].terminate()
            trainer._procs[0].join(timeout=5)
            assert not trainer._procs[0].is_alive()

            with pytest.raises(RuntimeError, match='worker 0'):
                trainer.run_iteration(0)
