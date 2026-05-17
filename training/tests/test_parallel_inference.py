"""End-to-end test for the parallel self-play pool.

Starts the ``ParallelInferencePool`` with n_workers=2, dispatches a
handful of games, verifies workers produce valid trajectory dicts
that plug into the replay buffer. This is the integration smoke for
the worker + inference-server + main-process wiring.
"""

from __future__ import annotations

import os

import pytest

from training.paradigms.az.buffer import ReplayBuffer
from training.paradigms.az.config import smoke_config
from training.paradigms.az.inference_pool import ParallelInferencePool

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


class TestParallelInferencePool:
    def test_workers_produce_valid_trajectories(self):
        cfg = smoke_config(data_dir=DATA_DIR)
        cfg.n_workers = 2
        cfg.n_games = 4
        pool = ParallelInferencePool(cfg)
        pool.start()
        try:
            for i in range(cfg.n_games):
                pool.dispatch(game_idx=i, env_seed=cfg.seed + i)

            buf = ReplayBuffer(capacity=1000)
            seen = 0
            while seen < cfg.n_games:
                res = pool.next_result(timeout=60)
                assert 'game_static' in res
                assert 'steps' in res
                assert res['winner'] in (0, 1, 2)
                assert res['n_steps'] > 0
                buf.add_trajectory(res['game_static'], res['steps'])
                seen += 1
            assert len(buf) > 0
        finally:
            pool.stop()

    def test_virtual_loss_path_plays_games(self):
        """parallel_rollouts>1 routes self-play through
        ``mcts_search_parallel`` with virtual loss + async RPC.
        Smoke that the full pipeline returns valid trajectories
        (we don't assert bit-equal with the sync path; the
        ordering of eval responses differs)."""
        cfg = smoke_config(data_dir=DATA_DIR)
        cfg.n_workers = 2
        cfg.n_games = 4
        cfg.mcts.parallel_rollouts = 4
        pool = ParallelInferencePool(cfg)
        pool.start()
        try:
            for i in range(cfg.n_games):
                pool.dispatch(game_idx=i, env_seed=cfg.seed + i)
            seen = 0
            total_steps = 0
            while seen < cfg.n_games:
                res = pool.next_result(timeout=60)
                assert res['n_steps'] > 0
                assert res['winner'] in (0, 1, 2)
                # Every step should have a legal_mask and a pi_target that
                # sums to ~1 on the legal slots.
                for step in res['steps']:
                    legal = step['legal_mask']
                    pi = step['pi_target']
                    assert (pi[~legal] == 0).all()
                    s = pi[legal].sum()
                    assert abs(s - 1.0) < 1e-4, f'pi_target sum on legal: {s}'
                total_steps += res['n_steps']
                seen += 1
            assert total_steps > 0
        finally:
            pool.stop()
