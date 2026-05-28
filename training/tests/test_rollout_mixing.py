"""Unit tests for the AlphaGo-mode leaf evaluation mixing.

Exercises ``_apply_leaf_mixing`` and ``_random_rollout_value`` from
``training/mcts.py`` with synthetic inputs so that regressions in
the blending arithmetic or the rollout path don't slip through.
"""

from __future__ import annotations

import random
from collections import deque

import numpy as np
import pytest

from training.paradigms.az.mcts import (
    MCTSConfig,
    MCTSNode,
    _apply_leaf_mixing,
    _random_rollout_value,
    compute_annealed_lambda,
)


class TestApplyLeafMixing:
    """Pure-function tests for prior + value blending."""

    def _node_with_children(self, legal_ids, priors):
        node = MCTSNode(turn=0, terminal=False)
        for aid, p in zip(legal_ids, priors):
            node.children[aid] = MCTSNode(turn=-1, terminal=False, prior=p)
        node.leaf_value_p0 = 0.8
        node.expanded = True
        return node

    def test_lambda_1_no_change(self):
        """lambda=1 means pure network — mixing should not change anything."""
        aids = [(0, 1, -1, -1, -1, ()), (3, -1, -1, -1, -1, ())]
        node = self._node_with_children(aids, [0.7, 0.3])
        cfg = MCTSConfig(value_mix_lambda=1.0, prior_mix_lambda=1.0)
        _apply_leaf_mixing(node, aids, cfg, rollout_v_p0=-0.5)
        assert node.leaf_value_p0 == 0.8
        assert node.children[aids[0]].prior == 0.7
        assert node.children[aids[1]].prior == 0.3

    def test_lambda_0_pure_rollout_and_uniform(self):
        """lambda=0 means pure rollout value + uniform prior."""
        aids = [(0, 1, -1, -1, -1, ()), (3, -1, -1, -1, -1, ())]
        node = self._node_with_children(aids, [0.9, 0.1])
        cfg = MCTSConfig(value_mix_lambda=0.0, prior_mix_lambda=0.0)
        _apply_leaf_mixing(node, aids, cfg, rollout_v_p0=-1.0)
        assert node.leaf_value_p0 == -1.0
        assert abs(node.children[aids[0]].prior - 0.5) < 1e-6
        assert abs(node.children[aids[1]].prior - 0.5) < 1e-6

    def test_lambda_half_blends(self):
        """lambda=0.5 should give a 50/50 blend."""
        aids = [(0, 1, -1, -1, -1, ())]
        node = self._node_with_children(aids, [0.8])
        node.leaf_value_p0 = 0.6
        cfg = MCTSConfig(value_mix_lambda=0.5, prior_mix_lambda=0.5)
        _apply_leaf_mixing(node, aids, cfg, rollout_v_p0=-0.4)
        assert abs(node.leaf_value_p0 - (0.5 * 0.6 + 0.5 * (-0.4))) < 1e-6
        assert abs(node.children[aids[0]].prior - (0.5 * 0.8 + 0.5 * 1.0)) < 1e-6

    def test_no_rollout_value_skips_value_mix(self):
        """When rollout_v_p0 is None, value should stay unchanged
        regardless of lambda."""
        aids = [(0, 1, -1, -1, -1, ())]
        node = self._node_with_children(aids, [0.6])
        node.leaf_value_p0 = 0.5
        cfg = MCTSConfig(value_mix_lambda=0.0, prior_mix_lambda=0.0)
        _apply_leaf_mixing(node, aids, cfg, rollout_v_p0=None)
        assert node.leaf_value_p0 == 0.5
        # prior still gets mixed (uniform)
        assert abs(node.children[aids[0]].prior - 1.0) < 1e-6

    def test_empty_legal_ids_no_crash(self):
        node = MCTSNode(turn=0, terminal=True)
        node.leaf_value_p0 = 1.0
        cfg = MCTSConfig(value_mix_lambda=0.0, prior_mix_lambda=0.0)
        _apply_leaf_mixing(node, [], cfg, rollout_v_p0=0.0)
        assert node.leaf_value_p0 == 0.0  # value still mixed


class TestComputeAnnealedLambda:
    """Tests for the per-game lambda annealing schedule."""

    def test_game_zero_returns_lambda_start(self):
        cfg = MCTSConfig(lambda_anneal_games=1000, lambda_start=0.0, lambda_end=0.8)
        assert compute_annealed_lambda(cfg, 0) == 0.0

    def test_game_at_anneal_games_returns_lambda_end(self):
        cfg = MCTSConfig(lambda_anneal_games=1000, lambda_start=0.0, lambda_end=0.8)
        assert compute_annealed_lambda(cfg, 1000) == 0.8

    def test_beyond_anneal_games_clamped_at_end(self):
        cfg = MCTSConfig(lambda_anneal_games=1000, lambda_start=0.0, lambda_end=0.8)
        assert compute_annealed_lambda(cfg, 2000) == 0.8

    def test_midpoint(self):
        cfg = MCTSConfig(lambda_anneal_games=1000, lambda_start=0.0, lambda_end=1.0)
        assert abs(compute_annealed_lambda(cfg, 500) - 0.5) < 1e-9

    def test_nonzero_start(self):
        cfg = MCTSConfig(lambda_anneal_games=100, lambda_start=0.2, lambda_end=0.6)
        assert abs(compute_annealed_lambda(cfg, 50) - 0.4) < 1e-9

    def test_raises_when_anneal_disabled(self):
        cfg = MCTSConfig(lambda_anneal_games=0)
        with pytest.raises(ValueError):
            compute_annealed_lambda(cfg, 0)


class TestRandomRolloutValue:
    """Tests for _random_rollout_value with a real GicgEnv."""

    def test_returns_finite_value(self):
        import os
        from gicg_env import GicgEnv

        data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
        env = GicgEnv(['赤蝶'], ['赤蝶'], seed=42, data_dir=data_dir)
        env.reset(seed=42)
        while env.phase == 1:
            env.step(0)
            if env.done:
                break
        try:
            rng = random.Random(123)
            v, steps = _random_rollout_value(env, 400, rng)
            assert v in (-1.0, 0.0, 1.0), f'unexpected rollout value: {v}'
            assert steps >= 0
            assert env.done
        finally:
            env.close()
