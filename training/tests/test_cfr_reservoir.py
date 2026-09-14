"""Tests for training/paradigms/cfr/legacy/reservoir."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from training.paradigms.cfr.reservoir import (
    AdvantageBuffer,
    StrategyBuffer,
    ValueBuffer,
)


# Fixtures -----------------------------------------------------------


N_SLOTS = 8
MAX_TOKENS = 4
MAX_HOOKS = 3
MAX_CHARS = 2
MAX_SKILLS = 2
MAX_ACTIONS = 5
META_SIZE = 19
N_STRUCTURAL = 4


def _game_static(k: int = 0) -> dict:
    # IR-4: opcode must be non-zero to count as a real op; k+1 keeps k=0
    # distinguishable from NOP padding.
    op_value = max(1, k + 1)
    return {
        'hook_ir': np.full((MAX_HOOKS, MAX_TOKENS, 5), op_value, dtype=np.int64),
        'hook_mask': np.array([True, True, False]),
        'counter_sids': np.arange(N_SLOTS, dtype=np.int64),
        'active_slot_mask': np.ones(N_SLOTS, dtype=bool),
        'char_skill_refs': np.full((2, MAX_CHARS, MAX_SKILLS), -1, dtype=np.int64),
        'definition_links': np.full((1, 2), -1, dtype=np.int64),
    }


def _sample_dynamic(k: int = 0) -> dict:
    return {
        'counter_values': np.full(N_SLOTS, float(k), dtype=np.float32),
        'buffs': np.array([[1, 0, -1, k + 1, 2, 3, 0, 0, 1, 0, 0, 0, 0, -1, -1, -1]], dtype=np.float32),
        'meta': np.zeros(META_SIZE, dtype=np.float32),
        'card_buckets': np.zeros((4, 10), dtype=np.float32),
        'enemy_sizes': np.ones(2, dtype=np.float32),
        'action_refs': np.zeros((MAX_ACTIONS, 3), dtype=np.int64),
        'action_payments': np.zeros((MAX_ACTIONS, 8), dtype=np.float32),
        'legal_mask': np.ones(MAX_ACTIONS, dtype=bool),
        'structural_values': np.zeros(N_STRUCTURAL, dtype=np.float32),
    }


def _advantage_target(k: int = 0) -> np.ndarray:
    return np.full(MAX_ACTIONS, float(k), dtype=np.float32)


def _policy_target() -> np.ndarray:
    p = np.ones(MAX_ACTIONS, dtype=np.float32) / MAX_ACTIONS
    return p


# Basic add + sample -------------------------------------------------


class TestAdvantageBasic:
    def test_add_within_capacity_lands(self):
        buf = AdvantageBuffer(capacity=4, max_actions=MAX_ACTIONS)
        rng = random.Random(0)
        gid = buf.register_game(_game_static(0))
        for k in range(3):
            landed = buf.add_sample(
                gid,
                _sample_dynamic(k),
                _advantage_target(k),
                iteration=1,
                rng=rng,
            )
            assert landed
        assert len(buf) == 3
        assert buf.stats()['size'] == 3

    def test_add_missing_dynamic_key_raises(self):
        buf = AdvantageBuffer(capacity=4, max_actions=MAX_ACTIONS)
        rng = random.Random(0)
        gid = buf.register_game(_game_static())
        bad = _sample_dynamic()
        del bad['meta']
        with pytest.raises(KeyError, match='meta'):
            buf.add_sample(gid, bad, _advantage_target(), iteration=1, rng=rng)

    def test_add_unknown_game_id_raises(self):
        buf = AdvantageBuffer(capacity=4, max_actions=MAX_ACTIONS)
        rng = random.Random(0)
        with pytest.raises(KeyError, match='game_id'):
            buf.add_sample(999, _sample_dynamic(), _advantage_target(), iteration=1, rng=rng)

    def test_target_shape_mismatch_raises(self):
        buf = AdvantageBuffer(capacity=4, max_actions=MAX_ACTIONS)
        rng = random.Random(0)
        gid = buf.register_game(_game_static())
        bad_target = np.zeros(MAX_ACTIONS + 1, dtype=np.float32)
        with pytest.raises(ValueError, match='target shape'):
            buf.add_sample(gid, _sample_dynamic(), bad_target, iteration=1, rng=rng)

    def test_zero_capacity_raises(self):
        with pytest.raises(ValueError, match='capacity'):
            AdvantageBuffer(capacity=0, max_actions=MAX_ACTIONS)

    def test_sample_empty_raises(self):
        buf = AdvantageBuffer(capacity=4, max_actions=MAX_ACTIONS)
        with pytest.raises(RuntimeError, match='empty'):
            buf.sample(2, random.Random(0))

    def test_sample_returns_batch_shape(self):
        buf = AdvantageBuffer(capacity=4, max_actions=MAX_ACTIONS)
        rng = random.Random(0)
        gid = buf.register_game(_game_static())
        for k in range(3):
            buf.add_sample(gid, _sample_dynamic(k), _advantage_target(k), iteration=1, rng=rng)
        batch = buf.sample(2, rng)
        assert batch['counter_values'].shape == (2, N_SLOTS)
        assert batch['regret'].shape == (2, MAX_ACTIONS)
        assert batch['action_refs'].shape == (2, MAX_ACTIONS, 3)
        assert batch['hook_mask'].shape[0] == 2


class TestStrategyBasic:
    def test_policy_target_shape(self):
        buf = StrategyBuffer(capacity=4, max_actions=MAX_ACTIONS)
        rng = random.Random(0)
        gid = buf.register_game(_game_static())
        buf.add_sample(gid, _sample_dynamic(), _policy_target(), iteration=1, rng=rng)
        batch = buf.sample(1, rng)
        assert batch['policy'].shape == (1, MAX_ACTIONS)


class TestValueBasic:
    def test_outcome_in_range(self):
        buf = ValueBuffer(capacity=4)
        rng = random.Random(0)
        gid = buf.register_game(_game_static())
        for z in (-1.0, 0.0, 1.0):
            landed = buf.add_sample(gid, _sample_dynamic(), z, iteration=1, rng=rng)
            assert landed
        batch = buf.sample(3, rng)
        assert batch['outcome'].shape == (3,)

    def test_outcome_out_of_range_raises(self):
        buf = ValueBuffer(capacity=4)
        rng = random.Random(0)
        gid = buf.register_game(_game_static())
        with pytest.raises(ValueError, match='outside'):
            buf.add_sample(gid, _sample_dynamic(), 1.5, iteration=1, rng=rng)


# Reservoir semantics ------------------------------------------------


class TestReservoirUniformity:
    def test_reservoir_holds_at_capacity(self):
        """After many adds, size stays exactly at capacity."""
        buf = AdvantageBuffer(capacity=10, max_actions=MAX_ACTIONS)
        rng = random.Random(42)
        gid = buf.register_game(_game_static())
        n_adds = 1000
        for k in range(n_adds):
            buf.add_sample(gid, _sample_dynamic(k), _advantage_target(k), iteration=1, rng=rng)
        assert len(buf) == 10
        assert buf.stats()['n_added_total'] == n_adds

    def test_reservoir_uniform_over_history(self):
        """Every k in [0, n_adds) has approximately equal probability
        of being in the final reservoir. Algorithm R gives
        P[item k in final] = capacity / n_adds for all k < n_adds when
        n_adds >= capacity.

        Per-bucket inclusion count across trials is Binomial(n_trials,
        capacity/n_adds), so σ = sqrt(n_trials × p × (1-p)). We assert
        all buckets fall within 4σ of expected; this catches off-by-one
        or systemic bias without false positives under healthy
        implementations. Previous bounds 0.4×..2.0× were so loose that
        a `j < capacity - 1` off-by-one would pass.
        """
        capacity = 20
        n_adds = 200
        n_trials = 500  # more trials → tighter empirical σ

        inclusion = np.zeros(n_adds, dtype=np.int64)
        for trial in range(n_trials):
            buf = AdvantageBuffer(capacity=capacity, max_actions=MAX_ACTIONS)
            rng = random.Random(trial)
            gid = buf.register_game(_game_static())
            for k in range(n_adds):
                tgt = np.zeros(MAX_ACTIONS, dtype=np.float32)
                tgt[0] = k
                buf.add_sample(gid, _sample_dynamic(), tgt, iteration=1, rng=rng)
            for e in buf._entries:
                k = int(e['regret'][0])
                inclusion[k] += 1

        p = capacity / n_adds
        expected = n_trials * p
        sigma = (n_trials * p * (1 - p)) ** 0.5
        tol = 4 * sigma
        assert inclusion.min() > expected - tol, (
            f'bucket under-represented: min={inclusion.min()} expected≈{expected:.1f} (4σ tol {tol:.1f})'
        )
        assert inclusion.max() < expected + tol, (
            f'bucket over-represented: max={inclusion.max()} expected≈{expected:.1f} (4σ tol {tol:.1f})'
        )

    def test_reservoir_always_full_after_capacity(self):
        """Once n_added >= capacity, size is always exactly capacity."""
        buf = AdvantageBuffer(capacity=5, max_actions=MAX_ACTIONS)
        rng = random.Random(7)
        gid = buf.register_game(_game_static())
        for k in range(50):
            buf.add_sample(gid, _sample_dynamic(), _advantage_target(k), iteration=1, rng=rng)
            if k + 1 >= 5:
                assert len(buf) == 5


# Per-game static dedup ----------------------------------------------


class TestGameStaticRefcount:
    @pytest.mark.parametrize('kind', ['advantage', 'strategy', 'value'])
    def test_replacing_only_sample_keeps_same_game_static(self, kind):
        cls = {'advantage': AdvantageBuffer, 'strategy': StrategyBuffer, 'value': ValueBuffer}[kind]
        buf = cls(capacity=1, **({'max_actions': MAX_ACTIONS} if kind != 'value' else {}))
        target = {'advantage': _advantage_target(), 'strategy': _policy_target(), 'value': 0.5}[kind]
        gid = buf.register_game(_game_static())
        rng = random.Random(1)  # accepts the second sample into slot zero
        assert buf.add_sample(gid, _sample_dynamic(0), target, iteration=1, rng=rng)
        assert buf.add_sample(gid, _sample_dynamic(1), target, iteration=2, rng=rng)
        assert buf._game_static[gid].refcount == 1
        batch = buf.sample(1, rng)
        np.testing.assert_array_equal(batch['counter_values'], np.ones((1, N_SLOTS)))

    def test_drops_static_when_all_samples_evicted(self):
        """A game that only contributes samples which all get evicted
        should have its static released."""
        buf = AdvantageBuffer(capacity=5, max_actions=MAX_ACTIONS)
        rng = random.Random(123)
        gid_old = buf.register_game(_game_static(0))
        # Fill buffer from game A
        for _ in range(5):
            buf.add_sample(gid_old, _sample_dynamic(), _advantage_target(), iteration=1, rng=rng)
        assert buf.n_games() == 1

        # Flood with adds from a new game; A's static refcount drops
        # as its entries are evicted. Eventually, A is gone.
        gid_new = buf.register_game(_game_static(1))
        for _ in range(10_000):
            buf.add_sample(gid_new, _sample_dynamic(), _advantage_target(), iteration=1, rng=rng)
        # Statistically, after 10000 replacements into a 5-slot
        # reservoir, game A's 5 original samples are all gone with
        # overwhelming probability.
        assert buf.n_games() == 1
        assert gid_old not in buf._game_static

    def test_multiple_games_coexist(self):
        """Two interleaved games both have static cached while samples
        from each remain in the buffer."""
        buf = AdvantageBuffer(capacity=10, max_actions=MAX_ACTIONS)
        rng = random.Random(456)
        gids = [buf.register_game(_game_static(k)) for k in range(3)]
        for gid in gids:
            for _ in range(2):
                buf.add_sample(gid, _sample_dynamic(), _advantage_target(), iteration=1, rng=rng)
        assert buf.n_games() == 3
        assert len(buf) == 6


# Save / load --------------------------------------------------------


class TestSaveLoad:
    def test_save_load_roundtrip(self, tmp_path):
        buf = AdvantageBuffer(capacity=8, max_actions=MAX_ACTIONS)
        rng = random.Random(0)
        gid = buf.register_game(_game_static(5))
        for k in range(5):
            buf.add_sample(
                gid,
                _sample_dynamic(k),
                _advantage_target(k),
                iteration=k,
                rng=rng,
            )

        path = tmp_path / 'buf.npz'
        buf.save(path)

        restored = AdvantageBuffer(capacity=8, max_actions=MAX_ACTIONS)
        restored.load(path)
        assert len(restored) == len(buf)
        assert restored.capacity == buf.capacity
        assert restored._n_added == buf._n_added
        assert restored.n_games() == buf.n_games()
        # Sample a batch from each using same rng — batches differ
        # due to fresh RNG seeds here, so only compare stored entries.
        for i, (orig, rest) in enumerate(zip(buf._entries, restored._entries)):
            assert orig['iteration'] == rest['iteration']
            np.testing.assert_array_equal(orig['regret'], rest['regret'])
            np.testing.assert_array_equal(orig['counter_values'], rest['counter_values'])
            np.testing.assert_array_equal(orig['buffs'], rest['buffs'])

    def test_save_load_value_buffer(self, tmp_path):
        buf = ValueBuffer(capacity=4)
        rng = random.Random(0)
        gid = buf.register_game(_game_static())
        for z in (-1.0, 1.0, 0.0):
            buf.add_sample(gid, _sample_dynamic(), z, iteration=1, rng=rng)

        path = tmp_path / 'val.npz'
        buf.save(path)

        restored = ValueBuffer(capacity=4)
        restored.load(path)
        assert len(restored) == 3
        for orig, rest in zip(buf._entries, restored._entries):
            assert orig['outcome'] == rest['outcome']
