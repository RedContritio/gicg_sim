"""Tests for the GICG Python engine bindings."""

import os
import pytest
import numpy as np

from gicg_env import GicgEngine
from gicg_env.engine import PHASE_GAME_OVER, PHASE_ACTION, ACTION_SKILL, ACTION_END_TURN

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


@pytest.fixture
def engine():
    eng = GicgEngine()
    yield eng


# F4: the engine no longer silently truncates an over-full eligible set
# (v_legacy 3v3 eligibility > 15), so the fixture pins the historical
# truncation-era composition explicitly (probe 2026-06-12, byte order).
GAME_DECK_P0 = [
    '乘胜追击',
    '以攻代守',
    '以牙还牙',
    '伏兵之术',
    '佛跳墙',
    '刺刺猫爪',
    '占星',
    '反制',
    '复刻',
    '守正',
    '清洁时间',
    '玄冰',
    '瞬身之术',
    '美味烧鸡',
    '荷花酥',
]
GAME_DECK_P1 = [
    '乘胜追击',
    '以攻代守',
    '以牙还牙',
    '伏兵之术',
    '佛跳墙',
    '刺刺猫爪',
    '占星',
    '反制',
    '发现静电',
    '复刻',
    '星愿',
    '清洁时间',
    '玄冰',
    '瞬身之术',
    '美味烧鸡',
]


@pytest.fixture
def game(engine):
    engine.new_game(
        players=[['赤蝶', '墨客', '猫咪'], ['刻师傅', '天星', '猫咪']],
        seed=42,
        data_dir=DATA_DIR,
        # Pre-ADR-0011 deck shape: 15 cards capped via 碌碌无为 padding.
        deck_padding={'card': '碌碌无为', 'target_size': 15},
        decks=[GAME_DECK_P0, GAME_DECK_P1],
    )
    # Advance past the PhaseSelectActive phase (both players pick char 0
    # as their initial active) so existing tests can assume PhaseAction.
    # Tests that want to exercise the select-active logic itself should
    # use the bare engine fixture.
    engine.step(0)
    engine.step(0)
    yield engine
    engine.close()


class TestGameCreation:
    def test_create_and_close(self, game):
        assert game.phase == PHASE_ACTION
        assert game.turn in (0, 1)

    def test_hand_count(self, game):
        assert game.hand_count(0) == 5
        assert game.hand_count(1) == 5

    def test_deck_count(self, game):
        assert game.deck_count(0) == 10
        assert game.deck_count(1) == 10

    def test_counters(self, game):
        counters = game.get_counters()
        assert len(counters) > 0
        assert counters.dtype == np.int32


class TestLegalActions:
    def test_has_legal_actions(self, game):
        kinds, indices = game.get_legal_actions()
        assert len(kinds) > 0
        assert len(kinds) == len(indices)

    def test_skills_available(self, game):
        game.set_player_dice(0, [0, 0, 0, 0, 0, 0, 0, 8])
        kinds, indices = game.get_legal_actions()
        assert ACTION_SKILL in kinds

    def test_end_turn_available(self, game):
        kinds, indices = game.get_legal_actions()
        assert ACTION_END_TURN in kinds


class TestGameplay:
    def test_step_skill(self, game):
        game.set_player_dice(0, [0, 0, 0, 0, 0, 0, 0, 8])
        kinds, indices = game.get_legal_actions()
        skill_idx = np.where(kinds == ACTION_SKILL)[0]
        assert len(skill_idx) > 0
        result = game.step(int(skill_idx[0]))
        assert result >= 0

    def test_both_end_turn(self, game):
        # P0 end turn
        kinds, _ = game.get_legal_actions()
        et_idx = np.where(kinds == ACTION_END_TURN)[0][0]
        game.step(int(et_idx))

        # P1 end turn
        kinds, _ = game.get_legal_actions()
        et_idx = np.where(kinds == ACTION_END_TURN)[0][0]
        game.step(int(et_idx))

        # Should have advanced to round 2 (still in action phase)
        assert game.phase == PHASE_ACTION


class TestRandomPlaythrough:
    def test_random_game_terminates(self, engine):
        """Play random actions until game ends or max steps reached."""
        engine.new_game(
            players=[['赤蝶', '墨客', '猫咪'], ['刻师傅', '天星', '猫咪']],
            seed=123,
            data_dir=DATA_DIR,
        )

        max_steps = 500
        for step in range(max_steps):
            if engine.done:
                break
            kinds, indices = engine.get_legal_actions()
            if len(kinds) == 0:
                break
            # Random action — this also handles PhaseSelectActive at the
            # start and any pending card targets (both appear as normal
            # legal actions via get_legal_actions).
            action_idx = np.random.randint(len(kinds))
            result = engine.step(int(action_idx))
            if result == 0:  # STEP_NEED_TARGET
                # Pick a random target from the now-pending target list.
                kinds, _ = engine.get_legal_actions()
                target_idx = np.random.randint(len(kinds)) if len(kinds) > 0 else 0
                engine.step_target(int(target_idx))

        engine.close()
        # Game should either end or reach max steps
        # (not crash or hang)


class TestMultipleGames:
    def test_create_multiple(self, engine):
        """Multiple games can coexist."""
        engine.new_game(
            players=[['赤蝶', '墨客', '猫咪'], ['刻师傅', '天星', '猫咪']],
            seed=1,
            data_dir=DATA_DIR,
        )
        c1 = engine.get_counters()
        engine.close()

        engine.new_game(
            players=[['赤蝶', '墨客', '猫咪'], ['刻师傅', '天星', '猫咪']],
            seed=2,
            data_dir=DATA_DIR,
        )
        c2 = engine.get_counters()
        engine.close()

        # Different seeds should give different states (due to shuffle)
        assert len(c1) == len(c2)
