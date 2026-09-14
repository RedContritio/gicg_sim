"""Unit tests for GreedyPlayer dice-payment optimization.

Covers both the pure dice-value scoring (hand-crafted views + pools,
expected ordering derivable by inspection) and the end-to-end filter
against a live env. See training/core/matchup/greedy_dice.py for
the heuristic rationale and the spec-quote this implements.
"""

from __future__ import annotations

import os

import numpy as np

from gicg_env import GicgEnv
from training.core.matchup.greedy_player import GreedyPlayer

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def _env():
    """Shared fixture: 赤蝶 vs 墨客 advanced past select-active phase."""
    env = GicgEnv(['赤蝶'], ['墨客'], data_dir=DATA_DIR)
    env.reset(seed=7)
    while env.phase == 1 and not env.done:
        env.step(0)
    return env


class TestDiceValueScoring:
    """build_color_values + payment_cost — the heuristic core. These
    tests hand-craft views + pools so the expected ordering is
    derivable by inspection."""

    def _view(self, me_active_elem: str, me_backline_elems: list[str]) -> dict:
        chars = [{'alive': True, 'element': me_active_elem}]
        for e in me_backline_elems:
            chars.append({'alive': True, 'element': e})
        return {
            'players': [
                {'chars': chars, 'active_char': 0},
                {'chars': [{'alive': True, 'element': 'none', 'hp': 10}], 'active_char': 0},
            ]
        }

    def test_active_color_outranks_backline(self):
        from training.core.matchup.greedy_dice import build_color_values

        view = self._view('fire', ['ice'])
        pool = np.array([1, 1, 1, 1, 1, 1, 1, 0], dtype=np.int32)
        values = build_color_values(view, me=0, dice_pool=pool)
        # fire=0 (active), ice=1 (backline); active >> backline
        assert values[0] > values[1]

    def test_backline_outranks_junk(self):
        from training.core.matchup.greedy_dice import build_color_values

        view = self._view('fire', ['ice'])
        # pool: 5 of water (junk, abundant), 1 of ice (backline)
        pool = np.array([0, 1, 5, 0, 0, 0, 0, 0], dtype=np.int32)
        values = build_color_values(view, me=0, dice_pool=pool)
        # ice (backline, tier 100) > water (5 * 10 = 50 junk)
        assert values[1] > values[2]

    def test_abundant_junk_outranks_rare_junk(self):
        from training.core.matchup.greedy_dice import build_color_values

        view = self._view('fire', [])
        # Pool: 5 of water, 1 of electro — neither relevant.
        pool = np.array([0, 0, 5, 1, 0, 0, 0, 0], dtype=np.int32)
        values = build_color_values(view, me=0, dice_pool=pool)
        # water junk (5*10=50) > electro junk (1*10=10)
        assert values[2] > values[3]

    def test_omni_above_backline(self):
        from training.core.matchup.greedy_dice import build_color_values

        view = self._view('fire', ['ice'])
        pool = np.array([1, 1, 0, 0, 0, 0, 0, 1], dtype=np.int32)
        values = build_color_values(view, me=0, dice_pool=pool)
        # Omni (7) tier 500 > ice backline tier 100
        assert values[7] > values[1]
        # but below active (fire, tier 1000)
        assert values[7] < values[0]

    def test_dead_backline_doesnt_count(self):
        """Backline chars that are dead should NOT contribute their
        element to the backline tier — their dice aren't useful anymore."""
        from training.core.matchup.greedy_dice import build_color_values

        view = {
            'players': [
                {
                    'chars': [
                        {'alive': True, 'element': 'fire'},
                        {'alive': False, 'element': 'ice'},
                    ],
                    'active_char': 0,
                },
                {'chars': [{'alive': True, 'element': 'none'}], 'active_char': 0},
            ]
        }
        pool = np.array([1, 1, 1, 1, 1, 1, 1, 0], dtype=np.int32)
        values = build_color_values(view, me=0, dice_pool=pool)
        # ice should only have junk tier (10), not backline (100)
        assert values[1] < 100

    def test_payment_cost_prefers_keeping_active(self):
        from training.core.matchup.greedy_dice import build_color_values, payment_cost

        view = self._view('fire', [])
        pool = np.array([3, 0, 3, 0, 0, 0, 0, 0], dtype=np.int32)
        values = build_color_values(view, me=0, dice_pool=pool)
        # Two payments for a 2-any cost: spend 2 fire OR spend 2 water
        pay_fire = np.array([2, 0, 0, 0, 0, 0, 0, 0], dtype=np.int32)
        pay_water = np.array([0, 0, 2, 0, 0, 0, 0, 0], dtype=np.int32)
        # Fire is active-color (tier 1000), water is junk (30);
        # MIN cost = water payment
        assert payment_cost(pay_water, values) < payment_cost(pay_fire, values)


class TestDiceFilterOnRealEnv:
    """End-to-end tests against a live env — the filter must return
    legal indices and collapse payment duplicates."""

    def test_filter_returns_only_legal_indices(self):
        from training.core.matchup.greedy_dice import filter_logical_actions

        env = _env()
        try:
            kinds, _ = env.get_legal_actions()
            n = len(kinds)
            chosen = filter_logical_actions(env)
            assert len(chosen) <= n
            for idx in chosen:
                assert 0 <= idx < n
            # Uniqueness: no duplicate indices.
            assert len(set(chosen)) == len(chosen)
        finally:
            env.close()

    def test_filter_keeps_one_per_identity(self):
        """Core contract: the filtered list has unique identity rows
        (collapse-by-identity is the whole point)."""
        from training.core.matchup.greedy_dice import filter_logical_actions

        env = _env()
        try:
            identities = env.get_action_identities()
            chosen = filter_logical_actions(env)
            seen_ids = set()
            for idx in chosen:
                key = tuple(int(x) for x in identities[idx])
                assert key not in seen_ids, f'duplicate identity {key} at idx {idx}'
                seen_ids.add(key)
        finally:
            env.close()

    def test_greedy_player_with_dice_greedy_picks_legal(self):
        env = _env()
        try:
            player = GreedyPlayer(features='F1', depth=1, seed=0, dice_greedy=True)
            idx = player.select_action(env)
            kinds, _ = env.get_legal_actions()
            assert 0 <= idx < len(kinds)
        finally:
            env.close()

    def test_greedy_player_both_modes_pick_legal(self):
        """Smoke test: toggling dice_greedy must never produce an
        illegal pick. Both modes are valid — we don't assert the
        picks are equal (heuristic may pick different payment for
        same logical action)."""
        for dg in (False, True):
            env = _env()
            try:
                player = GreedyPlayer(features='F2', depth=2, seed=0, dice_greedy=dg)
                idx = player.select_action(env)
                kinds, _ = env.get_legal_actions()
                assert 0 <= idx < len(kinds), f'dice_greedy={dg} picked {idx} out of {len(kinds)}'
            finally:
                env.close()

    def test_dice_counts_matches_pool_total(self):
        """env.dice_counts(player).sum() must equal dice_total(player)."""
        env = _env()
        try:
            for p in (0, 1):
                counts = env.dice_counts(p)
                assert counts.shape == (8,)
                assert counts.dtype == np.int32
                total = int(counts.sum())
                expected = int(env.dice_total(p))
                assert total == expected, f'player {p}: sum={total} vs dice_total={expected}'
        finally:
            env.close()
