"""Tests for training/paradigms/cfr/legacy/worker.py — spawns real subprocess workers.

Each test is slow (subprocess spin-up + DSL preload) so we keep the
number of tests small and the per-test work minimal."""

from __future__ import annotations

import multiprocessing as mp
import os

import pytest
import torch

from training.paradigms.cfr._collect_helpers import CFRGameBatch
from training.paradigms.cfr import AdvantageNet, CFRNetConfig
from training.paradigms.cfr.traversal import TraversalConfig
from training.paradigms.cfr.worker import (
    WorkError,
    WorkItem,
    WorkResult,
    WorkerConfig,
    spawn_worker,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
N_HOOKS_CAP = 900
MAX_TOK = 64
MAX_ACTIONS = 2048


def _worker_cfg() -> WorkerConfig:
    return WorkerConfig(
        net_cfg=CFRNetConfig(
            n_counter_slots=N_COUNTER_SLOTS,
            n_hooks=N_HOOKS_CAP,
            max_ops_per_hook=MAX_TOK,
            max_actions=MAX_ACTIONS,
            d_model=16,
            n_cross_layers=1,
            dropout=0.0,
        ),
        team_0=['赤蝶'],
        team_1=['墨客'],
        card_pool=None,
        data_dir=DATA_DIR,
        traversal=TraversalConfig(max_game_steps=400, epsilon=0.2),
    )


def _initial_weights(cfg: WorkerConfig) -> list:
    """Return [state_dict_p0, state_dict_p1] for WorkItem.weights_per_player."""
    torch.manual_seed(0)
    w0 = AdvantageNet(cfg.net_cfg).state_dict()
    torch.manual_seed(1)
    w1 = AdvantageNet(cfg.net_cfg).state_dict()
    return [
        {k: v.cpu() for k, v in w0.items()},
        {k: v.cpu() for k, v in w1.items()},
    ]


@pytest.fixture
def mp_ctx():
    # Use spawn on darwin/linux to avoid fork + cgo interactions.
    return mp.get_context('spawn')


class TestWorkerSingleItem:
    def test_worker_runs_work_item_and_returns_batches(self, mp_ctx):
        cfg = _worker_cfg()
        in_q = mp_ctx.Queue()
        out_q = mp_ctx.Queue()
        p = spawn_worker(0, cfg, in_q, out_q)
        try:
            weights = _initial_weights(cfg)
            in_q.put(
                WorkItem(
                    weights_per_player=weights,
                    n_traversals=2,
                    iteration=1,
                    seed_base=1000,
                    traverser_seq=[0, 1],
                )
            )
            result = out_q.get(timeout=180)
            assert isinstance(result, WorkResult), f'expected WorkResult, got {type(result)}: {result}'
            assert result.worker_id == 0
            assert len(result.batches) == 2
            # Traversal seq is [0, 1] — one game per player.
            for b, expected_traverser in zip(result.batches, [0, 1]):
                assert isinstance(b, CFRGameBatch)
                a0, a1, s_n, v_n = b.n_samples()
                assert v_n > 0  # every decision contributes to value
                # advantage only for the traverser's side
                if expected_traverser == 0:
                    assert a0 > 0 and a1 == 0
                    assert s_n == a0
                else:
                    assert a1 > 0 and a0 == 0
                    assert s_n == a1
        finally:
            in_q.put(None)  # shutdown
            p.join(timeout=30)
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)

    def test_worker_surfaces_exception_as_workerror(self, mp_ctx):
        """Send a malformed WorkItem (traverser_seq length != n_traversals).
        Worker should reply with WorkError and keep running."""
        cfg = _worker_cfg()
        in_q = mp_ctx.Queue()
        out_q = mp_ctx.Queue()
        p = spawn_worker(0, cfg, in_q, out_q)
        try:
            weights = _initial_weights(cfg)
            in_q.put(
                WorkItem(
                    weights_per_player=weights,
                    n_traversals=2,
                    iteration=1,
                    seed_base=0,
                    traverser_seq=[0],  # WRONG length
                )
            )
            result = out_q.get(timeout=60)
            assert isinstance(result, WorkError)
            assert 'traverser_seq' in result.traceback

            # Worker is still alive and able to process a follow-up item
            in_q.put(
                WorkItem(
                    weights_per_player=weights,
                    n_traversals=1,
                    iteration=1,
                    seed_base=100,
                    traverser_seq=[0],
                )
            )
            result2 = out_q.get(timeout=60)
            assert isinstance(result2, WorkResult)
            assert len(result2.batches) == 1
        finally:
            in_q.put(None)
            p.join(timeout=30)
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)

    def test_worker_shutdown_on_none(self, mp_ctx):
        """None on the queue terminates the worker cleanly (exit 0)."""
        cfg = _worker_cfg()
        in_q = mp_ctx.Queue()
        out_q = mp_ctx.Queue()
        p = spawn_worker(1, cfg, in_q, out_q)
        in_q.put(None)
        p.join(timeout=60)
        assert not p.is_alive()
        assert p.exitcode == 0
