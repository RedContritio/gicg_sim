"""Tests for training/paradigms/cfr/traversal."""

from __future__ import annotations

import os
import random

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.paradigms.cfr import AdvantageNet, CFRNetConfig
from training.paradigms.cfr.reservoir import (
    AdvantageBuffer,
    StrategyBuffer,
    ValueBuffer,
)
from training.paradigms.cfr.traversal import CFRTraverser, TraversalConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


# Network / buffer shape constants for the smoke game. These MUST match
# the engine's capacity (set at engine build time: 900 hooks, 120 tokens
# per hook) — the static obs layout encodes that size exactly.
D_MODEL = 8
MAX_TOK = 128
N_HOOKS_CAP = 900
MAX_ACTIONS = 2048
BUFFER_CAP = 2048


def _make_traverser(seed: int = 0):
    """Build a CFRTraverser for the smoke game (same fixture as the
    OS companion file; duplicated here to keep the files independent
    modulo shared imports)."""
    n_counter_slots = 2 * 6 * 128 + 2 * 140 + 16

    cfg = CFRNetConfig(
        n_counter_slots=n_counter_slots,
        n_hooks=N_HOOKS_CAP,
        max_ops_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )
    torch.manual_seed(seed)
    net = AdvantageNet(cfg)
    net.eval()
    return CFRTraverser(
        advantage_nets=[net, AdvantageNet(cfg)],
        n_counter_slots=n_counter_slots,
        max_ops_per_hook=MAX_TOK,
        n_hooks_capacity=N_HOOKS_CAP,
        max_actions=MAX_ACTIONS,
        advantage_buffers=[
            AdvantageBuffer(capacity=BUFFER_CAP, max_actions=MAX_ACTIONS),
            AdvantageBuffer(capacity=BUFFER_CAP, max_actions=MAX_ACTIONS),
        ],
        strategy_buffer=StrategyBuffer(capacity=BUFFER_CAP, max_actions=MAX_ACTIONS),
        value_buffer=ValueBuffer(capacity=BUFFER_CAP),
        rng=random.Random(seed),
    )


class TestTraverseSmoke:
    def test_traverse_reaches_terminal(self):
        """One outcome-sampling traversal on a real GicgEnv reaches a
        terminal state and tallies stats consistent with the game
        length."""
        t = _make_traverser(seed=42)
        env = GicgEnv(['赤蝶'], ['墨客'], seed=42, data_dir=DATA_DIR)
        env.reset(seed=42)
        try:
            stats = t.traverse(env, traverser_player=0, iteration=1)
            assert env.done, 'traversal did not leave env at terminal'
            assert stats.n_steps > 0
            # Every step is a decision (no pending-target states skipped)
            assert stats.n_steps == (stats.n_traverser_decisions + stats.n_opponent_decisions)
            # Value outcome is ±1 or 0
            assert stats.outcome_traverser in (-1.0, 0.0, 1.0)
            # Only traverser decisions fill advantage/strategy buffers
            assert stats.advantage_adds == stats.n_traverser_decisions
            assert stats.strategy_adds == stats.n_traverser_decisions
            # Value buffer gets every decision
            assert stats.value_adds == stats.n_steps
        finally:
            env.close()

    def test_buffers_populated_after_traversal(self):
        t = _make_traverser(seed=7)
        env = GicgEnv(['赤蝶'], ['墨客'], seed=7, data_dir=DATA_DIR)
        env.reset(seed=7)
        try:
            t.traverse(env, traverser_player=0, iteration=1)
            # Traverser P0 → only adv_p0 gets samples; adv_p1 empty
            assert len(t.advantage_buffers[0]) > 0
            assert len(t.advantage_buffers[1]) == 0
            assert len(t.strategy_buffer) > 0
            assert len(t.value_buffer) > 0
            # value adds ≥ advantage adds (opponent decisions also go to value)
            assert len(t.value_buffer) >= len(t.advantage_buffers[0])
        finally:
            env.close()

    def test_multiple_traversals_accumulate(self):
        """3 traversals (alternating P0/P1/P0) should grow total adv
        samples cumulatively across the per-player buffers."""
        t = _make_traverser(seed=3)
        totals = []
        for i in range(3):
            env = GicgEnv(['赤蝶'], ['墨客'], seed=100 + i, data_dir=DATA_DIR)
            env.reset(seed=100 + i)
            try:
                t.traverse(
                    env,
                    traverser_player=(i % 2),
                    iteration=i + 1,
                )
            finally:
                env.close()
            totals.append(len(t.advantage_buffers[0]) + len(t.advantage_buffers[1]))
        assert totals[0] > 0
        assert totals[1] > totals[0]
        assert totals[2] > totals[1]

    def test_strategy_policies_sum_to_one(self):
        """Every policy sample added to the strategy buffer sums to 1
        over legal slots (CFR derives its average strategy target from
        regret-matching, which is a valid distribution over legal)."""
        t = _make_traverser(seed=99)
        env = GicgEnv(['赤蝶'], ['墨客'], seed=99, data_dir=DATA_DIR)
        env.reset(seed=99)
        try:
            t.traverse(env, traverser_player=1, iteration=1)
        finally:
            env.close()

        for entry in t.strategy_buffer._entries:
            p = entry['policy']
            legal = entry['legal_mask']
            s = p[legal].sum()
            assert abs(s - 1.0) < 1e-4, f'policy sum {s} != 1'
            # illegal slots should be 0
            assert p[~legal].max() == 0.0

    def test_outcome_sign_matches_engine_winner(self):
        """After traversal: outcome_traverser should be +1 if the
        engine's winner is the traverser's player index, -1 if it's
        the opponent, 0 on draw. Verified by reading env.winner
        post-traversal and comparing against stats."""
        t = _make_traverser(seed=0)
        for traverser_player, seed in [(0, 300), (1, 301), (0, 302), (1, 303)]:
            env = GicgEnv(['赤蝶'], ['墨客'], seed=seed, data_dir=DATA_DIR)
            env.reset(seed=seed)
            try:
                stats = t.traverse(env, traverser_player=traverser_player, iteration=1)
                w = env.winner
            finally:
                env.close()
            if w == -1:
                assert stats.outcome_traverser == 0.0
            elif w == traverser_player:
                assert stats.outcome_traverser == 1.0
            else:
                assert stats.outcome_traverser == -1.0

    def test_mirror_match_same_chars_both_sides(self):
        """Mirror match (same char on both sides) is a first-class path
        per project convention — DSL is loaded per-binding and hooks
        must filter by owner. A traversal on 赤蝶 vs 赤蝶 must complete
        without crash and produce non-empty buffers."""
        t = _make_traverser(seed=31)
        env = GicgEnv(['赤蝶'], ['赤蝶'], seed=31, data_dir=DATA_DIR)
        env.reset(seed=31)
        try:
            stats = t.traverse(env, traverser_player=0, iteration=1)
        finally:
            env.close()
        assert stats.n_steps > 0
        assert stats.advantage_adds > 0
        assert stats.value_adds == stats.n_steps


# --------------------------------------------------------------------------- #
# Boundary / failure modes


class TestSampleAction:
    def _tvr(self):
        cfg = CFRNetConfig(
            n_counter_slots=16,
            n_hooks=16,
            max_ops_per_hook=4,
            max_actions=4,
            d_model=D_MODEL,
            n_cross_layers=1,
            dropout=0.0,
        )
        net = AdvantageNet(cfg)
        return CFRTraverser(
            advantage_nets=[net, AdvantageNet(cfg)],
            n_counter_slots=16,
            max_ops_per_hook=4,
            n_hooks_capacity=16,
            max_actions=4,
            advantage_buffers=[
                AdvantageBuffer(capacity=16, max_actions=4),
                AdvantageBuffer(capacity=16, max_actions=4),
            ],
            strategy_buffer=StrategyBuffer(capacity=16, max_actions=4),
            value_buffer=ValueBuffer(capacity=16),
            rng=random.Random(0),
        )

    def test_sample_action_raises_on_zero_q(self):
        t = self._tvr()
        q = np.zeros(4, dtype=np.float32)
        with pytest.raises(ValueError, match='sum'):
            t._sample_action(q, n_legal=3)

    def test_sample_action_raises_on_nan(self):
        t = self._tvr()
        q = np.array([0.5, float('nan'), 0.5, 0.0], dtype=np.float32)
        with pytest.raises(ValueError, match='non-finite'):
            t._sample_action(q, n_legal=3)

    def test_sample_action_distribution_matches(self):
        """Sample many times, compare empirical distribution to q."""
        t = self._tvr()
        q = np.array([0.1, 0.3, 0.6, 0.0], dtype=np.float32)
        counts = np.zeros(3, dtype=np.int64)
        for _ in range(10_000):
            idx = t._sample_action(q, n_legal=3)
            counts[idx] += 1
        empirical = counts / counts.sum()
        expected = q[:3]
        np.testing.assert_allclose(empirical, expected, atol=0.02)


class TestSamplingDistValidation:
    def _tvr(self):
        cfg = CFRNetConfig(
            n_counter_slots=16,
            n_hooks=16,
            max_ops_per_hook=4,
            max_actions=4,
            d_model=D_MODEL,
            n_cross_layers=1,
            dropout=0.0,
        )
        net = AdvantageNet(cfg)
        return CFRTraverser(
            advantage_nets=[net, AdvantageNet(cfg)],
            n_counter_slots=16,
            max_ops_per_hook=4,
            n_hooks_capacity=16,
            max_actions=4,
            advantage_buffers=[
                AdvantageBuffer(capacity=16, max_actions=4),
                AdvantageBuffer(capacity=16, max_actions=4),
            ],
            strategy_buffer=StrategyBuffer(capacity=16, max_actions=4),
            value_buffer=ValueBuffer(capacity=16),
            rng=random.Random(0),
        )

    def test_rejects_policy_that_doesnt_sum_to_one(self):
        t = self._tvr()
        bad = np.array([0.3, 0.3, 0.3, 0.0], dtype=np.float32)  # sum = 0.9
        legal = np.array([True, True, True, False])
        with pytest.raises(ValueError, match='not ~1'):
            t._sampling_dist(bad, legal, n_legal=3)

    def test_rejects_zero_n_legal(self):
        t = self._tvr()
        with pytest.raises(ValueError, match='n_legal'):
            t._sampling_dist(np.zeros(4, dtype=np.float32), np.zeros(4, bool), n_legal=0)


class TestTraverseFailureModes:
    def test_max_steps_exceeded_raises(self):
        """Low max_game_steps should surface as a RuntimeError if the
        smoke game doesn't finish in time."""
        t = _make_traverser(seed=0)
        t.config = TraversalConfig(
            max_game_steps=3,  # unrealistically low
            epsilon=t.config.epsilon,
        )
        env = GicgEnv(['赤蝶'], ['墨客'], seed=0, data_dir=DATA_DIR)
        env.reset(seed=0)
        try:
            with pytest.raises(RuntimeError, match='max_game_steps'):
                t.traverse(env, traverser_player=0, iteration=1)
        finally:
            env.close()
