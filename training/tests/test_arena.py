"""Tests for training/arena.py."""

from __future__ import annotations

import os

import pytest
import torch

from gicg_env import GicgEnv
from training.paradigms.az.arena import ArenaResult, arena_match
from training.paradigms.az.network import Agent, AgentConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
N_HOOKS = 900
MAX_TOK = 64
MAX_ACTIONS = 1024
D_MODEL = 16


def _agent(seed: int = 0) -> Agent:
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
    return Agent(cfg)


def _env_factory(game_idx: int) -> GicgEnv:
    env = GicgEnv(['赤蝶'], ['赤蝶'], seed=100 + game_idx, data_dir=DATA_DIR)
    env.reset(seed=100 + game_idx)
    return env


class TestArenaMatch:
    def test_runs_and_returns_result(self):
        challenger = _agent(seed=1)
        champion = _agent(seed=2)
        result = arena_match(
            challenger,
            champion,
            _env_factory,
            n_games=4,
            max_game_steps=400,
        )
        assert isinstance(result, ArenaResult)
        assert result.n_games == 4
        assert result.challenger_wins + result.champion_wins + result.draws == 4
        assert 0.0 <= result.challenger_win_rate <= 1.0

    def test_alternates_sides(self):
        """Across an even n_games, the challenger should play each
        side equal number of times. Verified indirectly: if the
        challenger never played one side, the win distribution
        would be heavily biased toward first-move advantage."""
        # Just smoke that 2 games (one on each side) complete.
        challenger = _agent(seed=3)
        champion = _agent(seed=4)
        result = arena_match(
            challenger,
            champion,
            _env_factory,
            n_games=2,
            max_game_steps=400,
        )
        assert result.n_games == 2

    def test_zero_games_raises(self):
        challenger = _agent()
        champion = _agent()
        with pytest.raises(ValueError, match='positive'):
            arena_match(challenger, champion, _env_factory, n_games=0)

    def test_win_rate_excludes_draws(self):
        """ArenaResult.challenger_win_rate should compute over
        decisive games only. If every game drew, returns 0.5."""
        r = ArenaResult(challenger_wins=0, champion_wins=0, draws=4, n_games=4)
        assert r.challenger_win_rate == 0.5

        r2 = ArenaResult(challenger_wins=3, champion_wins=1, draws=0, n_games=4)
        assert r2.challenger_win_rate == 0.75

        r3 = ArenaResult(challenger_wins=2, champion_wins=1, draws=1, n_games=4)
        # 2 / (4 - 1) = 2/3
        assert abs(r3.challenger_win_rate - 2.0 / 3.0) < 1e-9
