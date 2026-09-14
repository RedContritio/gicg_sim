"""F4 explicit-deck contract tests against the real engine.

Covers: decks argument shape validation (new_game raises), explicit
deck multiset round-trip (incl. duplicates + padding fill), implicit
overflow fail-loud (silent truncation removed), padding-card-missing
fail-loud, and reset/clone deck-spec persistence."""

import os
from collections import Counter

import pytest

from gicg_env import GicgEngine, GicgEnv

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

PAD15 = {'card': '碌碌无为', 'target_size': 15}

# Truncation-era effective 15-card deck for the v_legacy 赤蝶 mirror
# (probe 2026-06-12, byte order) — padding is a no-op for this list.
DECK15 = [
    '乘胜追击',
    '以攻代守',
    '以牙还牙',
    '伏兵之术',
    '佛跳墙',
    '占星',
    '反制',
    '清洁时间',
    '玄冰',
    '瞬身之术',
    '美味烧鸡',
    '荷花酥',
    '蝶鳞',
    '西风长枪',
    '诅咒',
]


def _deck_multiset(env: GicgEnv, player: int) -> Counter:
    names = env._engine.get_card_names()
    refs = list(env._engine.hand_refs(player)) + list(env._engine.deck_refs(player))
    return Counter(names[r] for r in refs)


class TestDecksArgValidation:
    def test_wrong_length_raises(self):
        eng = GicgEngine()
        with pytest.raises(ValueError, match='exactly 2 entries'):
            eng.new_game(players=[['赤蝶'], ['赤蝶']], data_dir=DATA_DIR, decks=[DECK15])

    def test_non_sequence_raises(self):
        eng = GicgEngine()
        with pytest.raises(TypeError, match='2-entry list/tuple'):
            eng.new_game(players=[['赤蝶'], ['赤蝶']], data_dir=DATA_DIR, decks={'0': DECK15, '1': DECK15})

    def test_str_entry_raises(self):
        eng = GicgEngine()
        with pytest.raises(TypeError, match='decks\\[1\\]'):
            eng.new_game(players=[['赤蝶'], ['赤蝶']], data_dir=DATA_DIR, decks=[DECK15, '佛跳墙'])

    def test_env_ctor_str_entry_raises(self):
        # GicgEnv keeps str entries unconverted so new_game can reject them.
        with pytest.raises(TypeError, match='decks\\[0\\]'):
            GicgEnv(['赤蝶'], ['赤蝶'], data_dir=DATA_DIR, decks=['佛跳墙', None])

    def test_empty_deck_entry_raises(self):
        # Empty list ≠ implicit path (that's None) — unexpected input
        # raises instead of silently building an all-filler deck.
        eng = GicgEngine()
        with pytest.raises(ValueError, match='decks\\[0\\] is an empty list'):
            eng.new_game(players=[['赤蝶'], ['赤蝶']], data_dir=DATA_DIR, decks=[[], DECK15])


class TestFailLoud:
    def test_implicit_overflow_raises(self):
        # v_legacy 赤蝶-mirror eligibility (17) > 15 — pre-F4 this
        # silently truncated; now game creation fails.
        with pytest.raises(RuntimeError, match='Failed to create game'):
            GicgEnv(['赤蝶'], ['赤蝶'], data_dir=DATA_DIR, deck_padding=PAD15)

    def test_unknown_deck_card_raises(self):
        with pytest.raises(RuntimeError, match='Failed to create game'):
            GicgEnv(
                ['赤蝶'],
                ['赤蝶'],
                card_pool=['佛跳墙'],
                data_dir=DATA_DIR,
                deck_padding=PAD15,
                decks=[['不存在的卡'], None],
            )

    def test_padding_card_missing_raises(self):
        # 1 eligible card < target needs padding, but the padding card
        # is not in the pool — pre-F4 this silently built a short deck.
        with pytest.raises(RuntimeError, match='Failed to create game'):
            GicgEnv(
                ['赤蝶'],
                ['赤蝶'],
                card_pool=['佛跳墙'],
                data_dir=DATA_DIR,
                deck_padding={'card': '不存在的填充卡', 'target_size': 15},
            )


class TestExplicitDeckRoundtrip:
    def test_full_deck_multiset(self):
        env = GicgEnv(['赤蝶'], ['赤蝶'], data_dir=DATA_DIR, deck_padding=PAD15, decks=[DECK15, DECK15])
        try:
            env.reset(seed=42)
            for p in (0, 1):
                assert _deck_multiset(env, p) == Counter(DECK15), f'P{p} deck != declared multiset'
        finally:
            env.close()

    def test_duplicates_and_padding_fill(self):
        env = GicgEnv(
            ['赤蝶'],
            ['赤蝶'],
            card_pool=['佛跳墙'],
            data_dir=DATA_DIR,
            deck_padding={'card': '碌碌无为', 'target_size': 5},
            decks=[['佛跳墙', '佛跳墙', '佛跳墙'], ['佛跳墙']],
        )
        try:
            env.reset(seed=42)
            assert _deck_multiset(env, 0) == Counter({'佛跳墙': 3, '碌碌无为': 2})
            assert _deck_multiset(env, 1) == Counter({'佛跳墙': 1, '碌碌无为': 4})
        finally:
            env.close()

    def test_per_player_none_passthrough(self):
        # P0 explicit, P1 implicit (eligible 1 < target → padding path).
        env = GicgEnv(
            ['赤蝶'],
            ['赤蝶'],
            card_pool=['佛跳墙'],
            data_dir=DATA_DIR,
            deck_padding={'card': '碌碌无为', 'target_size': 3},
            decks=[['佛跳墙', '佛跳墙'], None],
        )
        try:
            env.reset(seed=42)
            assert _deck_multiset(env, 0) == Counter({'佛跳墙': 2, '碌碌无为': 1})
            assert _deck_multiset(env, 1) == Counter({'佛跳墙': 1, '碌碌无为': 2})
        finally:
            env.close()


class TestObsVocabInvariant:
    def test_static_obs_and_card_vocab_unchanged_by_decks(self):
        # F4 invariant: explicit decks pick from the declared card set,
        # never extend it — the obs card vocabulary is controlled by
        # card_pool alone, so static obs layout must be bit-identical
        # with and without decks under the same card_pool.
        kw = dict(
            card_pool=['佛跳墙', '占星', '玄冰'],
            data_dir=DATA_DIR,
            deck_padding={'card': '碌碌无为', 'target_size': 5},
        )
        env_a = GicgEnv(['赤蝶'], ['赤蝶'], **kw)
        try:
            # {ref: name} dict — compare the mapping itself (Go map
            # serialization order is random, so no order assertion).
            vocab_a = env_a._engine.get_card_names()
            static_a = env_a._static_obs_size
        finally:
            env_a.close()
        env_b = GicgEnv(['赤蝶'], ['赤蝶'], decks=[['佛跳墙', '佛跳墙'], ['占星']], **kw)
        try:
            vocab_b = env_b._engine.get_card_names()
            static_b = env_b._static_obs_size
        finally:
            env_b.close()
        assert static_a == static_b, f'static obs size forked on decks: {static_a} != {static_b}'
        assert vocab_a == vocab_b, f'card ref→name vocab forked on decks: {vocab_a} != {vocab_b}'


class TestDeckSpecPersistence:
    def test_reset_rebuilds_declared_deck(self):
        env = GicgEnv(['赤蝶'], ['赤蝶'], data_dir=DATA_DIR, deck_padding=PAD15, decks=[DECK15, DECK15])
        try:
            env.reset(seed=123)
            assert _deck_multiset(env, 0) == Counter(DECK15)
            env.reset(seed=456, deck_seeds=(7, 8))
            assert _deck_multiset(env, 0) == Counter(DECK15)
        finally:
            env.close()

    def test_clone_shares_deck_spec(self):
        env = GicgEnv(['赤蝶'], ['赤蝶'], data_dir=DATA_DIR, deck_padding=PAD15, decks=[DECK15, DECK15])
        try:
            env.reset(seed=42)
            twin = env.clone()
            try:
                assert twin._decks == [DECK15, DECK15]
                twin.reset(seed=99)
                assert _deck_multiset(twin, 0) == Counter(DECK15)
                assert _deck_multiset(twin, 1) == Counter(DECK15)
            finally:
                twin.close()
        finally:
            env.close()
