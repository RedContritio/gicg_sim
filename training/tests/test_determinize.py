"""Tests for training/determinize.py — the IS-MCTS hidden-state
sampler. See docs/az/determinization.md for the spec these tests
enforce."""

import os
import random

import numpy as np
import pytest

from gicg_env import GicgEnv
from training.tests._helpers import keep_all_rerolls
from training.paradigms.az.determinize import (
    HiddenState,
    SharedFixedPool,
    _subtract_public,
    apply_determinization,
    sample_hidden_state,
    sample_opponent_dice,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def _env(team_0, team_1, seed=42):
    env = GicgEnv(team_0, team_1, seed=seed, data_dir=DATA_DIR)
    env.reset(seed=seed)
    keep_all_rerolls(env)
    return env


def _initial_pool_refs(env, player):
    """Return the ref list used as a canonical test pool for
    SharedFixedPool. deck content isn't directly readable (only a
    count), so we assemble the pool from the visible hand plus
    enough filler copies of each hand ref to fit hand_size + deck_size.
    The tests only assert 'ref came from this pool' + legality,
    which doesn't care about exact composition."""
    view = env.export_view()
    pv = view['players'][player]
    hand_refs = [c['ref'] for c in (pv.get('hand') or [])]
    deck_count = int(pv.get('deck_count') or 0)
    if hand_refs:
        pool = list(hand_refs) + [hand_refs[0]] * deck_count
    else:
        pool = []
    return pool


class TestSubtractPublic:
    def test_removes_one_copy_per_discarded_card(self):
        pool = [10, 20, 20, 30, 30, 30]
        discard = [20, 30, 30]
        remaining = _subtract_public(pool, discard)
        assert sorted(remaining) == [10, 20, 30]

    def test_ignores_discard_refs_not_in_pool(self):
        pool = [1, 2, 3]
        remaining = _subtract_public(pool, [99])
        assert remaining == [1, 2, 3]

    def test_empty_discard_returns_pool_copy(self):
        pool = [5, 5, 7]
        remaining = _subtract_public(pool, [])
        assert remaining == pool
        remaining.append(42)
        assert pool == [5, 5, 7]


class TestSharedFixedPool:
    def test_sample_returns_full_pool_unchanged(self):
        refs = [10, 20, 30, 40, 50]
        spec = SharedFixedPool(refs)
        rng = random.Random(0)
        out = spec.sample_opponent_deck(rng, {})
        assert out == refs
        # Caller gets a fresh list (mutation isolation).
        out.append(999)
        assert spec.card_refs == refs


class TestSampleOpponentDice:
    def test_shape_and_total(self):
        rng = random.Random(123)
        dice = sample_opponent_dice(rng, total_count=8)
        assert dice.shape == (8,)
        assert dice.dtype == np.int32
        assert int(dice.sum()) == 8
        assert (dice >= 0).all()

    def test_zero_total_returns_zeros(self):
        rng = random.Random(0)
        dice = sample_opponent_dice(rng, total_count=0)
        assert int(dice.sum()) == 0
        assert dice.shape == (8,)

    def test_deterministic_given_seed(self):
        rng1 = random.Random(7)
        rng2 = random.Random(7)
        a = sample_opponent_dice(rng1, total_count=16)
        b = sample_opponent_dice(rng2, total_count=16)
        assert np.array_equal(a, b)

    def test_different_seeds_usually_differ(self):
        # Multinomial(16, [1/8]*8) has very low collision prob — if
        # two independent seeds match, something is wrong.
        a = sample_opponent_dice(random.Random(1), 16)
        b = sample_opponent_dice(random.Random(2), 16)
        assert not np.array_equal(a, b)


class TestSampleHiddenState:
    def test_hand_size_matches_view(self):
        env = _env(['赤蝶'], ['墨客'])
        pool = _initial_pool_refs(env, player=1)
        spec = SharedFixedPool(pool)
        rng = random.Random(42)
        hidden = sample_hidden_state(env, viewing_player=0, card_pool_spec=spec, rng=rng)

        view = env.export_view()
        expected_hand = len(view['players'][1].get('hand') or [])
        expected_deck = int(view['players'][1].get('deck_count') or 0)
        assert len(hidden.opponent_hand) == expected_hand
        assert len(hidden.opponent_deck) == expected_deck
        env.close()

    def test_sampled_refs_come_from_pool(self):
        env = _env(['赤蝶'], ['墨客'])
        pool = _initial_pool_refs(env, player=1)
        spec = SharedFixedPool(pool)
        rng = random.Random(1)
        hidden = sample_hidden_state(env, viewing_player=0, card_pool_spec=spec, rng=rng)
        pool_set = set(pool)
        for ref in hidden.opponent_hand + hidden.opponent_deck:
            assert ref in pool_set
        env.close()

    def test_deterministic_given_seed(self):
        env = _env(['赤蝶'], ['墨客'])
        pool = _initial_pool_refs(env, player=1)
        spec = SharedFixedPool(pool)
        h1 = sample_hidden_state(env, 0, spec, random.Random(99))
        h2 = sample_hidden_state(env, 0, spec, random.Random(99))
        assert h1.opponent_hand == h2.opponent_hand
        assert h1.opponent_deck == h2.opponent_deck
        env.close()

    def test_dice_sampled_when_total_given(self):
        env = _env(['赤蝶'], ['墨客'])
        pool = _initial_pool_refs(env, player=1)
        spec = SharedFixedPool(pool)
        hidden = sample_hidden_state(
            env,
            0,
            spec,
            random.Random(0),
            opponent_dice_total=8,
        )
        assert hidden.opponent_dice_colors is not None
        assert int(hidden.opponent_dice_colors.sum()) == 8
        env.close()

    def test_dice_skipped_when_total_none(self):
        env = _env(['赤蝶'], ['墨客'])
        pool = _initial_pool_refs(env, player=1)
        spec = SharedFixedPool(pool)
        hidden = sample_hidden_state(env, 0, spec, random.Random(0))
        assert hidden.opponent_dice_colors is None
        env.close()

    def test_sampler_excludes_discarded_refs(self):
        """End-to-end wiring test: when the opponent has a specific
        card_ref in their discard, sample_hidden_state must not
        place that ref in hand or deck. Uses a stub env exposing only
        the atomic getters sample_hidden_state is allowed to touch —
        never export_view."""

        class _StubEngine:
            def __init__(self, hand_size, deck_count, discard_refs):
                self._hand = hand_size
                self._deck = deck_count
                self._discard = list(discard_refs)

            def hand_count(self, player):
                return self._hand

            def deck_count(self, player):
                return self._deck

            def discard_refs(self, player):
                return list(self._discard)

            def dice_paid(self, player):
                return [0] * 8

            def dice_tuned_out(self, player):
                return [0] * 8

        class _StubEnv:
            def __init__(self, engine):
                self._engine = engine

        # opponent: hand of 2, deck of 1, 777 already publicly committed
        stub_env = _StubEnv(_StubEngine(hand_size=2, deck_count=1, discard_refs=[777]))

        # Pool contains the sentinel + several fillers. After
        # subtracting the discarded sentinel, the pool has 3 fillers
        # available for 2 hand + 1 deck = 3 slots exactly.
        pool = [111, 111, 111, 777]
        spec = SharedFixedPool(pool)

        # Run across many seeds; sentinel must never appear.
        for seed in range(40):
            hidden = sample_hidden_state(stub_env, viewing_player=0, card_pool_spec=spec, rng=random.Random(seed))
            assert 777 not in hidden.opponent_hand
            assert 777 not in hidden.opponent_deck
            # Sanity: everything we got came from the non-discarded pool.
            for ref in hidden.opponent_hand + hidden.opponent_deck:
                assert ref == 111

    def test_sample_hidden_state_does_not_call_export_view(self):
        """Contract check: sample_hidden_state must reach the game
        state via atomic getters only. A stub env whose export_view
        raises on call proves no accidental export_view path."""

        class _GuardedEngine:
            def hand_count(self, player):
                return 3

            def deck_count(self, player):
                return 5

            def discard_refs(self, player):
                return []

            def dice_paid(self, player):
                return [0] * 8

            def dice_tuned_out(self, player):
                return [0] * 8

        class _GuardedEnv:
            def __init__(self):
                self._engine = _GuardedEngine()

            def export_view(self):
                raise AssertionError(
                    'sample_hidden_state must not call env.export_view — that path leaks opponent hand contents'
                )

        env = _GuardedEnv()
        spec = SharedFixedPool([1, 2, 3, 4, 5, 6, 7, 8])
        # Must not raise.
        hidden = sample_hidden_state(env, viewing_player=0, card_pool_spec=spec, rng=random.Random(0))
        assert len(hidden.opponent_hand) == 3
        assert len(hidden.opponent_deck) == 5

    def test_clamps_when_pool_too_small(self):
        """Pool exhausted edge case: pool smaller than hand+deck.
        Sampler must clamp instead of raising."""
        env = _env(['赤蝶'], ['墨客'])
        # Intentionally shrink the pool to 1 ref — smaller than any
        # realistic opponent hand+deck.
        view = env.export_view()
        any_ref = view['players'][0]['hand'][0]['ref']
        tiny_spec = SharedFixedPool([any_ref])
        hidden = sample_hidden_state(env, 0, tiny_spec, random.Random(0))
        total = len(hidden.opponent_hand) + len(hidden.opponent_deck)
        assert total <= 1
        env.close()


class TestApplyDeterminization:
    def test_injects_hand_and_deck(self):
        env = _env(['赤蝶'], ['墨客'])
        view_before = env.export_view()
        any_ref = view_before['players'][0]['hand'][0]['ref']

        hidden = HiddenState(
            opponent_hand=[any_ref, any_ref],
            opponent_deck=[any_ref, any_ref, any_ref],
        )
        apply_determinization(env, hidden, opponent=1)

        view_after = env.export_view()
        assert len(view_after['players'][1]['hand']) == 2
        assert view_after['players'][1]['deck_count'] == 3
        env.close()

    def test_viewing_player_state_untouched(self):
        env = _env(['赤蝶', '墨客'], ['猫咪', '刻师傅'])
        view_before = env.export_view()
        p0_hp = [c['hp'] for c in view_before['players'][0]['chars']]
        p0_hand = [c['ref'] for c in view_before['players'][0]['hand']]
        p0_deck = view_before['players'][0]['deck_count']

        any_ref = view_before['players'][1]['hand'][0]['ref']
        hidden = HiddenState(
            opponent_hand=[any_ref],
            opponent_deck=[any_ref, any_ref],
        )
        apply_determinization(env, hidden, opponent=1)

        view_after = env.export_view()
        assert [c['hp'] for c in view_after['players'][0]['chars']] == p0_hp
        assert [c['ref'] for c in view_after['players'][0]['hand']] == p0_hand
        assert view_after['players'][0]['deck_count'] == p0_deck
        env.close()

    def test_applies_dice_when_present(self):
        """HiddenState.opponent_dice_colors must be applied via the
        new set_player_dice path. We read back via the dynamic obs's
        dice counter slots (labeled P1:dice_<color>) and verify the
        counts round-trip end-to-end."""
        env = _env(['赤蝶'], ['墨客'])
        dice_vec = np.array([3, 0, 2, 0, 0, 0, 0, 1], dtype=np.int32)  # fire=3, water=2, omni=1
        hidden = HiddenState(
            opponent_hand=[],
            opponent_deck=[],
            opponent_dice_colors=dice_vec,
        )
        apply_determinization(env, hidden, opponent=1)

        # ActiveCounterSlotLabels is generated under perspective=0
        # (canonical ordering): own=P0 first, enemy=P1 second. Read
        # obs under the SAME perspective so label indices align with
        # obs indices — otherwise the perspective swap puts P0's
        # values where P1's labels claim to be.
        obs = env.get_dynamic_obs(perspective=0)
        labels = env._engine.get_active_counter_slot_labels()
        # Skip the versioned meta header; counter values follow.
        from gicg_env.engine import DICE_COLOR_COUNT
        from gicg_env import OBS_META_SIZE

        meta_size = OBS_META_SIZE

        want = {
            'P1:dice_fire': 3,
            'P1:dice_water': 2,
            'P1:dice_omni': 1,
            'P1:dice_ice': 0,
        }
        found = 0
        for needle, wanted in want.items():
            for i, lbl in enumerate(labels):
                if lbl == needle:
                    got = int(obs[meta_size + i])
                    assert got == wanted, f'{needle}={got}, want {wanted}'
                    found += 1
                    break
            else:
                raise AssertionError(f'label {needle!r} not in labels')
        assert found == len(want)
        env.close()

    def test_survives_snapshot_restore(self):
        """The canonical MCTS pattern: snapshot root, apply
        determinization, roll forward, restore. Verify the determinized
        state is actually live between apply and restore."""
        env = _env(['赤蝶'], ['墨客'])
        snap = env.snapshot()
        try:
            view_before = env.export_view()
            any_ref = view_before['players'][0]['hand'][0]['ref']
            hidden = HiddenState(
                opponent_hand=[any_ref, any_ref, any_ref],
                opponent_deck=[],
            )
            apply_determinization(env, hidden, opponent=1)
            view_applied = env.export_view()
            assert len(view_applied['players'][1]['hand']) == 3

            env.restore(snap)
            view_restored = env.export_view()
            assert len(view_restored['players'][1]['hand']) == len(view_before['players'][1]['hand'])
        finally:
            env.snapshot_free(snap)
        env.close()
