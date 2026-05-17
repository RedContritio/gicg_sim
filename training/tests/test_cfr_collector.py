"""Tests for training/paradigms/cfr/legacy/collector.py."""

from __future__ import annotations

import pickle
import random

import numpy as np
import pytest

from training.paradigms.cfr._collect_helpers import (
    CFRGameBatch,
    CollectorBuffer,
    drain_single_traversal,
    ingest_batches,
)
from training.paradigms.cfr.reservoir import (
    AdvantageBuffer,
    StrategyBuffer,
    ValueBuffer,
)


# Same fixture layout as test_cfr_reservoir
N_SLOTS = 8
MAX_TOKENS = 4
MAX_HOOKS = 3
MAX_CHARS = 2
MAX_SKILLS = 2
MAX_ACTIONS = 5
META_SIZE = 3
N_STRUCTURAL = 4


def _game_static(k: int = 0) -> dict:
    return {
        'hook_types': np.full((MAX_HOOKS, MAX_TOKENS), k, dtype=np.int64),
        'hook_values': np.full((MAX_HOOKS, MAX_TOKENS), float(k), dtype=np.float32),
        'hook_mask': np.array([True, True, False]),
        'counter_sids': np.arange(N_SLOTS, dtype=np.int64),
        'active_slot_mask': np.ones(N_SLOTS, dtype=bool),
        'char_skill_refs': np.full((2, MAX_CHARS, MAX_SKILLS), -1, dtype=np.int64),
    }


def _sample_dynamic(k: int = 0) -> dict:
    return {
        'counter_values': np.full(N_SLOTS, float(k), dtype=np.float32),
        'meta': np.zeros(META_SIZE, dtype=np.float32),
        'card_buckets': np.zeros((4, 10), dtype=np.float32),
        'enemy_sizes': np.ones(2, dtype=np.float32),
        'action_refs': np.zeros((MAX_ACTIONS, 3), dtype=np.int64),
        'action_payments': np.zeros((MAX_ACTIONS, 8), dtype=np.float32),
        'legal_mask': np.ones(MAX_ACTIONS, dtype=bool),
        'structural_values': np.zeros(N_STRUCTURAL, dtype=np.float32),
    }


def _regret(k: int = 0) -> np.ndarray:
    return np.full(MAX_ACTIONS, float(k), dtype=np.float32)


# --------------------------------------------------------------------------- #
# CollectorBuffer


class TestCollectorBuffer:
    def test_register_and_add(self):
        c = CollectorBuffer()
        gid = c.register_game(_game_static(1))
        for k in range(5):
            landed = c.add_sample(gid, _sample_dynamic(k), _regret(k), iteration=1)
            assert landed
        assert len(c) == 5

    def test_no_eviction_with_many_adds(self):
        c = CollectorBuffer()
        gid = c.register_game(_game_static())
        for k in range(1000):
            c.add_sample(gid, _sample_dynamic(), _regret(k), iteration=1)
        assert len(c) == 1000

    def test_missing_static_key_raises(self):
        c = CollectorBuffer()
        bad = _game_static()
        del bad['hook_types']
        with pytest.raises(KeyError, match='hook_types'):
            c.register_game(bad)

    def test_unknown_game_id_raises(self):
        c = CollectorBuffer()
        with pytest.raises(KeyError, match='unknown gid'):
            c.add_sample(42, _sample_dynamic(), _regret(), iteration=1)

    def test_missing_dynamic_key_raises(self):
        c = CollectorBuffer()
        gid = c.register_game(_game_static())
        bad = _sample_dynamic()
        del bad['meta']
        with pytest.raises(KeyError, match='meta'):
            c.add_sample(gid, bad, _regret(), iteration=1)

    def test_drain_batches_preserves_gid_order(self):
        c = CollectorBuffer()
        gids = []
        for i in range(3):
            gid = c.register_game(_game_static(i))
            c.add_sample(gid, _sample_dynamic(i), _regret(i), iteration=i)
            gids.append(gid)
        batches = c.drain_batches()
        assert len(batches) == 3
        for i, (static, samples) in enumerate(batches):
            assert len(samples) == 1
            # hook_types entries were filled with k=i in _game_static
            assert int(static['hook_types'][0, 0]) == i
            # target was _regret(i) filled with i
            assert float(samples[0][1][0]) == float(i)

    def test_drain_clears(self):
        c = CollectorBuffer()
        c.register_game(_game_static())
        c.drain_batches()
        assert len(c) == 0
        # Can register a new game from a clean state
        gid = c.register_game(_game_static())
        assert gid == 0  # gid counter reset

    def test_sample_copy_isolation(self):
        """Caller mutating the passed arrays should not affect stored data."""
        c = CollectorBuffer()
        gid = c.register_game(_game_static())
        dyn = _sample_dynamic()
        target = _regret(3)
        c.add_sample(gid, dyn, target, iteration=1)
        # Mutate caller's copies
        dyn['meta'].fill(999.0)
        target.fill(-1.0)
        batches = c.drain_batches()
        (static, samples) = batches[0]
        stored_dyn, stored_target, _ = samples[0]
        assert stored_dyn['meta'].max() == 0.0
        assert float(stored_target[0]) == 3.0


# --------------------------------------------------------------------------- #
# CFRGameBatch / collect_batches


class TestDrainSingleTraversal:
    def test_drain_traverser_0(self):
        adv_cols = [CollectorBuffer(), CollectorBuffer()]
        strat = CollectorBuffer()
        val = CollectorBuffer()
        # Simulate traversal with traverser=0: register in adv_cols[0],
        # strat, and val only.
        a0 = adv_cols[0].register_game(_game_static(5))
        s = strat.register_game(_game_static(5))
        v = val.register_game(_game_static(5))
        adv_cols[0].add_sample(a0, _sample_dynamic(), _regret(), iteration=1)
        strat.add_sample(s, _sample_dynamic(), _regret(), iteration=1)
        val.add_sample(v, _sample_dynamic(), 1.0, iteration=1)

        batch = drain_single_traversal(adv_cols, strat, val, traverser_player=0)
        assert batch.n_samples() == (1, 0, 1, 1)

    def test_drain_traverser_1(self):
        adv_cols = [CollectorBuffer(), CollectorBuffer()]
        strat = CollectorBuffer()
        val = CollectorBuffer()
        a1 = adv_cols[1].register_game(_game_static(3))
        s = strat.register_game(_game_static(3))
        v = val.register_game(_game_static(3))
        adv_cols[1].add_sample(a1, _sample_dynamic(), _regret(), iteration=1)
        strat.add_sample(s, _sample_dynamic(), _regret(), iteration=1)
        val.add_sample(v, _sample_dynamic(), -1.0, iteration=1)

        batch = drain_single_traversal(adv_cols, strat, val, traverser_player=1)
        assert batch.n_samples() == (0, 1, 1, 1)

    def test_wrong_slot_populated_raises(self):
        """If both adv collectors have samples for the same traversal
        (should never happen), drain_single_traversal raises."""
        adv_cols = [CollectorBuffer(), CollectorBuffer()]
        strat = CollectorBuffer()
        val = CollectorBuffer()
        for p in range(2):
            g = adv_cols[p].register_game(_game_static())
            adv_cols[p].add_sample(g, _sample_dynamic(), _regret(), iteration=1)
        s = strat.register_game(_game_static())
        v = val.register_game(_game_static())
        strat.add_sample(s, _sample_dynamic(), _regret(), iteration=1)
        val.add_sample(v, _sample_dynamic(), 0.0, iteration=1)
        with pytest.raises(RuntimeError, match='non-traverser'):
            drain_single_traversal(adv_cols, strat, val, traverser_player=0)


# --------------------------------------------------------------------------- #
# Pickle round-trip (required for Queue transport)


class TestPickleRoundTrip:
    def test_batch_pickle_roundtrip(self):
        batch = CFRGameBatch(
            static=_game_static(5),
            advantage_samples_per_player=[
                [(_sample_dynamic(), _regret(3), 1)],
                [],
            ],
            strategy_samples=[(_sample_dynamic(), _regret(2), 1)],
            value_samples=[(_sample_dynamic(), 1.0, 1)],
        )
        restored = pickle.loads(pickle.dumps(batch))
        assert restored.n_samples() == batch.n_samples()
        np.testing.assert_array_equal(
            restored.static['hook_types'],
            batch.static['hook_types'],
        )
        np.testing.assert_array_equal(
            restored.advantage_samples_per_player[0][0][1],
            batch.advantage_samples_per_player[0][0][1],
        )
        assert restored.value_samples[0][1] == 1.0


# --------------------------------------------------------------------------- #
# ingest_batches: merge into central reservoir


class TestIngestBatches:
    def test_replay_into_reservoirs(self):
        # Build 2 game-worth of samples (one with traverser=0, one with
        # traverser=1) via the drain_single_traversal path.
        batches = []
        for g, traverser_p in [(0, 0), (1, 1)]:
            adv_cols = [CollectorBuffer(), CollectorBuffer()]
            strat_c = CollectorBuffer()
            val_c = CollectorBuffer()
            a = adv_cols[traverser_p].register_game(_game_static(g))
            s = strat_c.register_game(_game_static(g))
            v = val_c.register_game(_game_static(g))
            for k in range(3):
                adv_cols[traverser_p].add_sample(
                    a,
                    _sample_dynamic(),
                    _regret(k),
                    iteration=1,
                )
                strat_c.add_sample(s, _sample_dynamic(), _regret(k), iteration=1)
                val_c.add_sample(v, _sample_dynamic(), 0.1, iteration=1)
            batches.append(
                drain_single_traversal(
                    adv_cols,
                    strat_c,
                    val_c,
                    traverser_p,
                )
            )

        transported = pickle.loads(pickle.dumps(batches))

        adv_bs = [
            AdvantageBuffer(capacity=20, max_actions=MAX_ACTIONS),
            AdvantageBuffer(capacity=20, max_actions=MAX_ACTIONS),
        ]
        strat_b = StrategyBuffer(capacity=20, max_actions=MAX_ACTIONS)
        val_b = ValueBuffer(capacity=20)
        n_a0, n_a1, n_s, n_v = ingest_batches(
            transported,
            adv_bs,
            strat_b,
            val_b,
            random.Random(0),
        )
        # Each player's adv buffer received 3 samples from ITS one
        # traversal. Strategy / value got 3+3=6 each (one per game).
        assert n_a0 == 3
        assert n_a1 == 3
        assert n_s == 6
        assert n_v == 6
        assert len(adv_bs[0]) == 3
        assert len(adv_bs[1]) == 3
        assert len(strat_b) == 6
        assert len(val_b) == 6

    def test_empty_batches_noop(self):
        adv_bs = [
            AdvantageBuffer(capacity=10, max_actions=MAX_ACTIONS),
            AdvantageBuffer(capacity=10, max_actions=MAX_ACTIONS),
        ]
        strat_b = StrategyBuffer(capacity=10, max_actions=MAX_ACTIONS)
        val_b = ValueBuffer(capacity=10)
        n = ingest_batches([], adv_bs, strat_b, val_b, random.Random(0))
        assert n == (0, 0, 0, 0)
