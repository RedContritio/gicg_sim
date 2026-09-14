"""Tests for training/matchup.py."""

from __future__ import annotations

import os

import pytest
import torch

from training.core.matchup.loaders import load_player
from training.core.matchup.matchup import (
    CellStats,
    MatchupResult,
    enumerate_disjoint_teams,
    run_matchup,
)
from training.paradigms.az.network import Agent, AgentConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
N_HOOKS = 900
MAX_TOK = 128
MAX_ACTIONS = 1024
D_MODEL = 16


def _agent_ckpt(tmp_path, seed: int = 0) -> str:
    torch.manual_seed(seed)
    cfg = AgentConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=N_HOOKS,
        max_ops_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )
    agent = Agent(cfg)
    ckpt = tmp_path / f'ckpt_seed{seed}.pt'
    agent.save(str(ckpt))
    return str(ckpt)


# --------------------------------------------------------------------------- #
# enumerate_disjoint_teams


class TestEnumerateDisjointTeams:
    def test_5_pool_team_size_2_yields_15(self):
        pool = ['A', 'B', 'C', 'D', 'E']
        pairs = enumerate_disjoint_teams(pool, 2)
        assert len(pairs) == 15
        # Every char appears in at most team_size * len(pool) total
        # team-positions but never both teams in same pair
        for t0, t1 in pairs:
            assert len(t0) == 2
            assert len(t1) == 2
            assert not (set(t0) & set(t1)), f'overlap: {t0} ∩ {t1}'

    def test_4_pool_team_size_2_yields_3(self):
        pool = ['A', 'B', 'C', 'D']
        pairs = enumerate_disjoint_teams(pool, 2)
        # Partition 4 into 2+2, unordered → 3
        assert len(pairs) == 3
        for t0, t1 in pairs:
            assert set(t0 + t1) == set(pool)

    def test_unordered_no_duplicates(self):
        """({A,B} vs {C,D}) and ({C,D} vs {A,B}) fold into one entry."""
        pool = ['A', 'B', 'C', 'D']
        pairs = enumerate_disjoint_teams(pool, 2)
        seen = set()
        for t0, t1 in pairs:
            key = frozenset([frozenset(t0), frozenset(t1)])
            assert key not in seen, f'duplicate pair: {t0} vs {t1}'
            seen.add(key)

    def test_pool_smaller_than_2x_team_size_raises(self):
        with pytest.raises(ValueError, match='team_size=2'):
            enumerate_disjoint_teams(['A', 'B', 'C'], 2)

    def test_zero_team_size_raises(self):
        with pytest.raises(ValueError, match='positive'):
            enumerate_disjoint_teams(['A', 'B'], 0)


# --------------------------------------------------------------------------- #
# load_player dispatch


class TestLoadPlayer:
    def test_random_loader(self):
        builder = load_player({'type': 'random'})
        p = builder(seed=0)
        assert p is not None
        # builder called again gives an independent instance
        p2 = builder(seed=1)
        assert p is not p2

    def test_mcts_pure_rejects_zero_simulations(self):
        with pytest.raises(ValueError, match='n_simulations'):
            load_player({'type': 'mcts_pure', 'n_simulations': 0})

    def test_mcts_pure_valid(self):
        builder = load_player({'type': 'mcts_pure', 'n_simulations': 4})
        p = builder(seed=0)
        assert p.n_rollouts == 4

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match='unknown player type'):
            load_player({'type': 'bogus'})

    def test_missing_type_raises(self):
        with pytest.raises(ValueError, match="missing 'type'"):
            load_player({})

    def test_az_loader_argmax(self, tmp_path):
        ckpt = _agent_ckpt(tmp_path, seed=1)
        builder = load_player({'type': 'az', 'ckpt': ckpt, 'n_simulations': 0})
        p = builder(seed=0)
        assert p is not None


# --------------------------------------------------------------------------- #
# run_matchup end-to-end


class TestRunMatchup:
    def test_az_vs_random_fixed_teams(self, tmp_path):
        ckpt = _agent_ckpt(tmp_path, seed=2)
        result = run_matchup(
            players=[
                {'type': 'az', 'ckpt': ckpt, 'n_simulations': 0},
                {'type': 'random'},
            ],
            mode='fixed',
            team_0=['赤蝶'],
            team_1=['墨客'],
            games_per_cell=1,
            max_game_steps=400,
            data_dir=DATA_DIR,
            seed=42,
        )
        assert isinstance(result, MatchupResult)
        assert result.aggregate.n_games == 2  # 1 per side
        assert 0.0 <= result.aggregate.win_rate <= 1.0
        assert len(result.per_cell) == 1

    def test_random_vs_random_enumerate(self, tmp_path):
        """Enumerate mode with no ckpt dependency — random vs random,
        pool of 3 chars, team_size=1 → 3 matchups."""
        result = run_matchup(
            players=[{'type': 'random'}, {'type': 'random'}],
            mode='enumerate_disjoint',
            char_pool=['赤蝶', '墨客', '猫咪'],
            team_size=1,
            games_per_cell=1,
            max_game_steps=400,
            data_dir=DATA_DIR,
            seed=0,
        )
        # 3 choose 1 × 2 choose 1 / 2 = 3
        assert len(result.per_cell) == 3
        # Each cell: 2 games (side-swap with games_per_cell=1)
        total_games = sum(c['n_games'] for c in result.per_cell)
        assert total_games == 6
        assert result.aggregate.n_games == 6

    def test_rejects_non_two_players(self):
        with pytest.raises(ValueError, match='expected 2 players'):
            run_matchup(
                players=[{'type': 'random'}],
                mode='fixed',
                team_0=['赤蝶'],
                team_1=['墨客'],
                games_per_cell=1,
                data_dir=DATA_DIR,
            )

    def test_rejects_zero_games_per_cell(self):
        with pytest.raises(ValueError, match='games_per_cell'):
            run_matchup(
                players=[{'type': 'random'}, {'type': 'random'}],
                mode='fixed',
                team_0=['赤蝶'],
                team_1=['墨客'],
                games_per_cell=0,
                data_dir=DATA_DIR,
            )

    def test_fixed_mode_requires_teams(self):
        with pytest.raises(ValueError, match='team_0'):
            run_matchup(
                players=[{'type': 'random'}, {'type': 'random'}],
                mode='fixed',
                games_per_cell=1,
                data_dir=DATA_DIR,
            )

    def test_enumerate_mode_requires_char_pool(self):
        with pytest.raises(ValueError, match='char_pool'):
            run_matchup(
                players=[{'type': 'random'}, {'type': 'random'}],
                mode='enumerate_disjoint',
                games_per_cell=1,
                data_dir=DATA_DIR,
            )

    def test_no_swap_runs_only_primary_side(self):
        """With ``swap_sides=False``, the cell plays exactly
        ``games_per_cell`` games and primary never sits on P1. n_games
        must equal games_per_cell (not 2× like the default)."""
        result = run_matchup(
            players=[{'type': 'random'}, {'type': 'random'}],
            mode='fixed',
            team_0=['赤蝶'],
            team_1=['墨客'],
            games_per_cell=3,
            data_dir=DATA_DIR,
            seed=7,
            swap_sides=False,
        )
        assert result.aggregate.n_games == 3  # not 6

    def test_swap_default_doubles_games(self):
        """Default (``swap_sides=True``) keeps the legacy contract:
        cell plays 2 × games_per_cell games alternating sides."""
        result = run_matchup(
            players=[{'type': 'random'}, {'type': 'random'}],
            mode='fixed',
            team_0=['赤蝶'],
            team_1=['墨客'],
            games_per_cell=3,
            data_dir=DATA_DIR,
            seed=7,
        )
        assert result.aggregate.n_games == 6


# --------------------------------------------------------------------------- #
# CellStats


class TestCellStats:
    def test_win_rate_excludes_draws(self):
        s = CellStats(wins=3, losses=1, draws=0)
        assert s.win_rate == 0.75

    def test_win_rate_all_draws_half(self):
        s = CellStats(wins=0, losses=0, draws=4)
        assert s.win_rate == 0.5

    def test_win_rate_mixed(self):
        s = CellStats(wins=1, losses=1, draws=2)
        assert s.win_rate == 0.5

    def test_n_games(self):
        s = CellStats(wins=2, losses=3, draws=1)
        assert s.n_games == 6
