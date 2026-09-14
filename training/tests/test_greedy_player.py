"""Unit tests for GreedyPlayer feature/depth variants.

Uses a fixed 1v1 env; not testing absolute win rates (depends on
scenario), only that the player picks SOMETHING legal and that the
depth axis actually changes pick behavior on adversarial positions.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from gicg_env import GicgEnv, REWARD_EVENTS_COUNT, REWARD_EVENTS_FIELDS
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.matchup.greedy_scorers import (
    _ap_waste_piecewise,
    _kill_slope_escalating,
    _score_f1,
    _score_f2,
    _score_f3,
    _score_f4,
    _score_f5,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
_IDX = {name: i for i, name in enumerate(REWARD_EVENTS_FIELDS)}


def _zev() -> np.ndarray:
    """Zero events vector — convenient F1/F2-only callers don't care."""
    return np.zeros(REWARD_EVENTS_COUNT, dtype=np.int32)


def _ev(**kwargs) -> np.ndarray:
    """Build an events vector from keyword args mapping field name →
    value. Any unset field stays 0. Raises KeyError on a typo, which
    catches renames before they silently drop to a useless test."""
    arr = np.zeros(REWARD_EVENTS_COUNT, dtype=np.int32)
    for k, v in kwargs.items():
        arr[_IDX[k]] = v
    return arr


def _env():
    env = GicgEnv(['赤蝶'], ['墨客'], data_dir=DATA_DIR)
    env.reset(seed=7)
    # Walk through PHASE_SELECT_ACTIVE so we land on a real action node
    while env.phase == 1 and not env.done:
        env.step(0)
    return env


class TestScoringPrimitives:
    def test_f1_dmg_dealt_positive(self):
        view_before = {
            'players': [
                {'chars': [{'hp': 10, 'alive': True}]},
                {'chars': [{'hp': 10, 'alive': True}]},
            ]
        }
        view_after = {
            'players': [
                {'chars': [{'hp': 10, 'alive': True}]},
                {'chars': [{'hp': 7, 'alive': True}]},
            ]
        }
        # I'm player 0, I dealt 3 to enemy, took 0
        assert _score_f1(view_before, view_after, _zev(), _zev(), me=0) == pytest.approx(3.0)

    def test_f1_asymmetric_reception(self):
        view_before = {
            'players': [
                {'chars': [{'hp': 10, 'alive': True}]},
                {'chars': [{'hp': 10, 'alive': True}]},
            ]
        }
        # I took 2, dealt 0 — score = -1.1 * 2 = -2.2
        view_after = {
            'players': [
                {'chars': [{'hp': 8, 'alive': True}]},
                {'chars': [{'hp': 10, 'alive': True}]},
            ]
        }
        assert _score_f1(view_before, view_after, _zev(), _zev(), me=0) == pytest.approx(-2.2)

    def test_f2_kill_bonus(self):
        view_before = {
            'players': [
                {'chars': [{'hp': 5, 'alive': True}]},
                {'chars': [{'hp': 5, 'alive': True}]},
            ]
        }
        # I killed enemy — alive 1 → 0 → +10; also dealt 5 dmg
        view_after = {
            'players': [
                {'chars': [{'hp': 5, 'alive': True}]},
                {'chars': [{'hp': 0, 'alive': False}]},
            ]
        }
        score = _score_f2(view_before, view_after, _zev(), _zev(), me=0)
        # F1 part = 5; +10 for kill; no death
        assert score == pytest.approx(15.0)

    def test_f2_death_penalty(self):
        view_before = {
            'players': [
                {'chars': [{'hp': 3, 'alive': True}]},
                {'chars': [{'hp': 10, 'alive': True}]},
            ]
        }
        # I died: own alive 1 → 0 → -8; F1 part = -1.1 * 3 = -3.3
        view_after = {
            'players': [
                {'chars': [{'hp': 0, 'alive': False}]},
                {'chars': [{'hp': 10, 'alive': True}]},
            ]
        }
        score = _score_f2(view_before, view_after, _zev(), _zev(), me=0)
        assert score == pytest.approx(-3.3 - 8.0)


class TestF3F4F5Primitives:
    def _flat_view(self):
        v = {
            'players': [
                {'chars': [{'hp': 10, 'alive': True}]},
                {'chars': [{'hp': 10, 'alive': True}]},
            ]
        }
        # Unchanged view — keeps the F1/F2 base at 0 so we can test
        # the F3/F4/F5 increment in isolation.
        return v, v

    def test_f3_adds_heal_delta_with_asymmetric_weight(self):
        vb, va = self._flat_view()
        before = _ev()
        after = _ev(heal_done=4, enemy_heal_done=5)
        # F2 base = 0; F3 increment = 4 - 0.8 * 5 = 0
        assert _score_f3(vb, va, before, after, me=0) == pytest.approx(0.0)

    def test_f3_positive_when_only_i_heal(self):
        vb, va = self._flat_view()
        before = _ev()
        after = _ev(heal_done=3)
        assert _score_f3(vb, va, before, after, me=0) == pytest.approx(3.0)

    def test_f4_adds_shield_and_reaction(self):
        vb, va = self._flat_view()
        before = _ev()
        after = _ev(shield_absorbed=5, damage_blocked=2, reactions_triggered=2, reactions_received=1)
        # F3 increment = 0; F4 increment = (5 - 0.8*2) + (2 - 0.8*1) = 3.4 + 1.2 = 4.6
        assert _score_f4(vb, va, before, after, me=0) == pytest.approx(4.6)

    def test_f4_stacks_on_f3_contributions(self):
        vb, va = self._flat_view()
        before = _ev()
        after = _ev(heal_done=2, shield_absorbed=5)
        # F3 adds heal_done=2; F4 adds shield_absorbed=5 → total 7
        assert _score_f4(vb, va, before, after, me=0) == pytest.approx(7.0)

    def test_f5_energy_overflow_penalty(self):
        vb, va = self._flat_view()
        before = _ev()
        after = _ev(energy_overflow=3)
        # F4 base = 0; F5 penalty = -0.4 * 3 = -1.2
        assert _score_f5(vb, va, before, after, me=0) == pytest.approx(-1.2)

    def test_f5_ap_waste_piecewise(self):
        vb, va = self._flat_view()
        before = _ev()
        after = _ev(ap_wasted=4)
        # piecewise(4) = 0.2*3 + 0.5*1 = 0.6 + 0.5 = 1.1; F5 adds -1.1
        assert _score_f5(vb, va, before, after, me=0) == pytest.approx(-1.1)

    def test_f5_escalating_kill_slope_on_top_of_f2_flat(self):
        # First kill of the game: total_before=0, so slope adds
        # 5*0 = 0 — this test locks the "no escalation on the opening
        # kill" property. F2 flat bonus (+10) is still present.
        vb = {
            'players': [
                {'chars': [{'hp': 5, 'alive': True}]},
                {'chars': [{'hp': 5, 'alive': True}]},
            ]
        }
        va = {
            'players': [
                {'chars': [{'hp': 5, 'alive': True}]},
                {'chars': [{'hp': 0, 'alive': False}]},
            ]
        }
        before = _ev(total_kills=0)
        after = _ev(kills=1, total_kills=1)
        # F2 = 5 (dmg) + 10 (flat kill) = 15; F5 adds 0 slope
        assert _score_f5(vb, va, before, after, me=0) == pytest.approx(15.0)

    def test_f5_escalating_slope_after_several_kills(self):
        # Two kills in this step; 3 prior kills. Slope adds
        # 5*(3+0) + 5*(3+1) = 15 + 20 = 35.
        vb, va = self._flat_view()  # Views unchanged — kills come from events
        before = _ev(total_kills=3)
        after = _ev(kills=2, total_kills=5)
        # F2 = 0 (view unchanged, so no alive-count kill delta); F5 only adds slope
        assert _score_f5(vb, va, before, after, me=0) == pytest.approx(35.0)

    def test_ap_waste_piecewise_breakpoints(self):
        # Exact breakpoints: 0, 3, 6, 8, 10
        assert _ap_waste_piecewise(0) == pytest.approx(0.0)
        assert _ap_waste_piecewise(3) == pytest.approx(0.6)
        assert _ap_waste_piecewise(6) == pytest.approx(0.6 + 1.5)  # 2.1
        assert _ap_waste_piecewise(8) == pytest.approx(2.1 + 1.6)  # 3.7
        assert _ap_waste_piecewise(10) == pytest.approx(3.7 + 2.0)  # 5.7

    def test_ap_waste_piecewise_clamps_negative(self):
        assert _ap_waste_piecewise(-5) == pytest.approx(0.0)

    def test_kill_slope_empty(self):
        assert _kill_slope_escalating(0, 10) == pytest.approx(0.0)

    def test_kill_slope_consecutive(self):
        # total_before=2, 3 kills: 5*2 + 5*3 + 5*4 = 10+15+20 = 45
        assert _kill_slope_escalating(3, 2) == pytest.approx(45.0)


class TestRewardEventsEnvAccess:
    def test_reward_events_shape_and_dtype(self):
        env = _env()
        try:
            ev = env.reward_events(0)
            assert ev.shape == (REWARD_EVENTS_COUNT,)
            assert ev.dtype == np.int32
        finally:
            env.close()

    def test_reward_events_accumulates_on_step(self):
        """Drive the env until damage lands; post-step events must
        weakly dominate pre-step for both players (counters are
        monotone-nondecreasing within an episode)."""
        env = _env()
        try:
            before_p0 = env.reward_events(0)
            before_p1 = env.reward_events(1)
            # Play up to 40 actions or terminal; monotonicity holds
            # regardless of whether damage actually lands.
            for _ in range(40):
                if env.done:
                    break
                kinds, _slots = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                env.step(0)
            after_p0 = env.reward_events(0)
            after_p1 = env.reward_events(1)
            assert np.all(after_p0 >= before_p0), (before_p0, after_p0)
            assert np.all(after_p1 >= before_p1), (before_p1, after_p1)
        finally:
            env.close()

    def test_reset_zeroes_reward_events(self):
        env = _env()
        try:
            # Advance a few steps so at least some counter moves.
            for _ in range(5):
                if env.done:
                    break
                kinds, _s = env.get_legal_actions()
                if len(kinds) == 0:
                    break
                env.step(0)
            env.reset(seed=7)
            ev = env.reward_events(0)
            assert np.all(ev == 0), ev
        finally:
            env.close()


class TestGreedyPlayerContract:
    def test_pick_returns_legal_index(self):
        env = _env()
        try:
            player = GreedyPlayer(features='F1', depth=1, seed=0)
            idx = player.select_action(env)
            kinds, _ = env.get_legal_actions()
            assert 0 <= idx < len(kinds)
        finally:
            env.close()

    def test_rejects_unknown_features(self):
        with pytest.raises(ValueError, match='unknown features'):
            GreedyPlayer(features='F99', depth=1)

    def test_rejects_bad_depth(self):
        # depth=4 now valid (DMC opp pool uses F1-D4); depth=5 still rejected
        with pytest.raises(ValueError, match='depth must be'):
            GreedyPlayer(features='F1', depth=5)

    def test_all_five_feature_variants_instantiate(self):
        for f in ('F1', 'F2', 'F3', 'F4', 'F5'):
            p = GreedyPlayer(features=f, depth=1, seed=0)
            assert p.cfg.features == f

    def test_f5_picks_legal_action(self):
        """F5 exercises reward_events plumbing end-to-end — if the
        accumulator read / binding / scoring chain has any wiring
        bug, selection either crashes or picks nonsense."""
        env = _env()
        try:
            player = GreedyPlayer(features='F5', depth=1, seed=0)
            idx = player.select_action(env)
            kinds, _ = env.get_legal_actions()
            assert 0 <= idx < len(kinds)
        finally:
            env.close()

    def test_env_restored_after_select(self):
        """select_action must not mutate env state."""
        env = _env()
        try:
            snap = env.snapshot()
            try:
                kinds_before, _ = env.get_legal_actions()
                view_before = env.export_view()
                player = GreedyPlayer(features='F1', depth=2, seed=0)
                _ = player.select_action(env)
                kinds_after, _ = env.get_legal_actions()
                view_after = env.export_view()
                assert len(kinds_after) == len(kinds_before)
                # HP unchanged — strongest invariant
                for p in (0, 1):
                    for ca, cb in zip(view_after['players'][p]['chars'], view_before['players'][p]['chars']):
                        assert ca['hp'] == cb['hp']
            finally:
                env.snapshot_free(snap)
        finally:
            env.close()


class TestMinimaxBudget:
    """C2 (2026-05-25): minimax_node_budget cfg knob for cross-language fair bench
    parity with Go `gicg_actor/dmc/greedy_player.go` MinimaxBudget。"""

    def test_default_unbounded(self):
        """minimax_node_budget=None (default) → unbounded recursion (production
        historical behavior)。"""
        p = GreedyPlayer(features='F1', depth=2, seed=0)
        assert p.minimax_node_budget is None

    def test_explicit_budget_stored(self):
        p = GreedyPlayer(features='F1', depth=4, seed=0, minimax_node_budget=4000)
        assert p.minimax_node_budget == 4000

    def test_rejects_zero_budget(self):
        """budget=0 鉴别不出 "unbounded" vs "全停"; 强制 > 0 或 None,fail-loud。"""
        with pytest.raises(ValueError, match='minimax_node_budget must be > 0 or None'):
            GreedyPlayer(features='F1', depth=4, seed=0, minimax_node_budget=0)

    def test_rejects_negative_budget(self):
        with pytest.raises(ValueError, match='minimax_node_budget must be > 0 or None'):
            GreedyPlayer(features='F1', depth=4, seed=0, minimax_node_budget=-1)

    def test_budget_caps_recursion(self):
        """tiny budget (=1) 必 cap 递归 — select_with_info 仍返合法 action,但
        scoring 深度被截。 D2 → depth-1 subtree at top level: budget=1 only allows
        ONE candidate to descend, rest score at top node directly。"""
        env = _env()
        try:
            # uncapped baseline — D2 full expansion
            full = GreedyPlayer(features='F1', depth=2, seed=0)
            full_idx, full_info = full.select_with_info(env)
            kinds, _ = env.get_legal_actions()
            assert 0 <= full_idx < len(kinds)
            n_scored = len(full_info['scored'])

            # capped D2 — budget=1 hits ceiling near immediately
            capped = GreedyPlayer(features='F1', depth=2, seed=0, minimax_node_budget=1)
            cap_idx, cap_info = capped.select_with_info(env)
            assert 0 <= cap_idx < len(kinds)
            # 仍 scored 全部 top-level candidates (budget 只截 sub-tree, top level
            # 强制每个 candidate 必 enter loop body 一次)。
            assert len(cap_info['scored']) == n_scored
            # 但 capped 的 scores 可能与 full 不同 (sub-tree score 被截后 fallback
            # 到 current-node score, top-level argmax 可能选 different action)。
            # 这里只 contract-test cap 不 crash + 返 legal idx; 行为差异留 winrate gate。
        finally:
            env.close()

    def test_budget_uncapped_equals_old_const(self):
        """C2 backward compat: uncapped (None) vs explicit large budget (1e9) 必产
        same action (large budget 实际上不会被打破)。"""
        env = _env()
        try:
            # Bound branching, not search depth: this tests budget equivalence,
            # not the default full-hand payment enumeration performance.
            for player in (0, 1):
                env._engine.set_player_hand(player, [])
                env._engine.set_player_deck(player, [])
                env._engine.set_player_dice(player, [0, 0, 0, 0, 0, 0, 0, 3])
            assert len(env.get_action_refs()) > 1
            unbounded = GreedyPlayer(features='F1', depth=4, seed=42).select_action(env)
            large_budget = GreedyPlayer(
                features='F1', depth=4, seed=42, minimax_node_budget=1_000_000_000
            ).select_action(env)
            assert unbounded == large_budget
        finally:
            env.close()


class TestLoaderRegistration:
    def test_greedy_loader_registered(self):
        from training.core.matchup.loaders import LOADERS

        assert 'greedy' in LOADERS

    def test_loader_builds_player(self):
        from training.core.matchup.loaders import load_player

        builder = load_player({'type': 'greedy', 'features': 'F2', 'depth': 1})
        player = builder(seed=0)
        assert isinstance(player, GreedyPlayer)
        assert player.cfg.features == 'F2'
        assert player.cfg.depth == 1

    def test_loader_defaults(self):
        from training.core.matchup.loaders import load_player

        builder = load_player({'type': 'greedy'})
        player = builder(seed=0)
        assert player.cfg.features == 'F1'
        assert player.cfg.depth == 1

    def test_loader_passes_dice_greedy(self):
        """dice_greedy must flow through loader → builder → player.
        Full filter semantics tested in test_greedy_dice.py."""
        from training.core.matchup.loaders import load_player

        builder = load_player({'type': 'greedy', 'dice_greedy': True})
        player = builder(seed=0)
        assert player.dice_greedy is True
        # Back-compat: omitted flag must default to False.
        builder2 = load_player({'type': 'greedy'})
        assert builder2(seed=0).dice_greedy is False
