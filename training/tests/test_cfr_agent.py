"""Tests for CFRAgent + matchup.py's cfr loader."""

from __future__ import annotations

import os

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.paradigms.cfr.agent import CFRAgent
from training.paradigms.cfr import CFRNetConfig, CFRStrategyNet
from training.core.matchup.loaders import LOADERS, load_player
from training.core.matchup.matchup import run_matchup

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
N_HOOKS_CAP = 900
MAX_TOK = 64
MAX_ACTIONS = 2048


def _cfg() -> CFRNetConfig:
    return CFRNetConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=N_HOOKS_CAP,
        max_ops_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )


def _make_ckpt(tmp_path, seed: int = 0) -> str:
    torch.manual_seed(seed)
    net = CFRStrategyNet(_cfg())
    path = tmp_path / f'cfr_seed{seed}.pt'
    net.save(str(path))
    return str(path)


# ------------------------------------------------------------------ #
# CFRAgent evaluator protocol


class TestCFRAgent:
    def test_load_and_eval_on_real_env(self, tmp_path):
        """CFRAgent.load → encode_static → eval_state produces a valid
        (prior, value) pair on a real GicgEnv decision point."""
        ckpt = _make_ckpt(tmp_path, seed=1)
        agent = CFRAgent(_cfg())
        agent.load(ckpt)

        env = GicgEnv(['赤蝶'], ['墨客'], seed=42, data_dir=DATA_DIR)
        env.reset(seed=42)
        # Advance past PHASE_SELECT_ACTIVE
        while env.phase == 1:
            env.step(0)
            if env.done:
                pytest.skip('game ended too early')

        agent.encode_static(env.static_obs)
        refs = env.get_action_refs()
        payments = env.get_legal_action_payments()
        dyn_obs = env._get_obs()
        prior, value = agent.eval_state(dyn_obs, refs, payments)

        n_legal = len(refs)
        assert prior.shape == (n_legal,)
        assert prior.min() >= 0.0
        assert abs(prior.sum() - 1.0) < 1e-5
        assert -1.0 <= value <= 1.0
        env.close()

    def test_eval_state_before_encode_static_raises(self, tmp_path):
        ckpt = _make_ckpt(tmp_path, seed=2)
        agent = CFRAgent(_cfg())
        agent.load(ckpt)
        refs = np.array([[0, 1, 0]], dtype=np.int32)
        payments = np.zeros((1, 8), dtype=np.float32)
        dyn = np.zeros(1000, dtype=np.float32)
        with pytest.raises(RuntimeError, match='game_start'):
            agent.eval_state(dyn, refs, payments)

    def test_rejects_non_cfr_ckpt(self, tmp_path):
        """CFRAgent.load rejects an AZ-format ckpt (different kind)."""
        # Save an "AZ-like" blob: {cfg, net, kind: 'az'}
        path = tmp_path / 'not_cfr.pt'
        torch.save({'cfg': {}, 'net': {}, 'kind': 'something_else'}, str(path))
        agent = CFRAgent(_cfg())
        with pytest.raises(RuntimeError, match='kind'):
            agent.load(str(path))


# ------------------------------------------------------------------ #
# matchup.py cfr loader


class TestCFRLoader:
    def test_cfr_in_loaders_registry(self):
        assert 'cfr' in LOADERS

    def test_load_cfr_builds_argmax_player(self, tmp_path):
        ckpt = _make_ckpt(tmp_path, seed=3)
        builder = load_player(
            {
                'type': 'cfr',
                'ckpt': ckpt,
                'n_simulations': 0,
            }
        )
        player = builder(seed=0)
        # argmax wrapper holds a CFRAgent in .agent
        assert isinstance(player.agent, CFRAgent)

    def test_load_cfr_builds_mcts_player(self, tmp_path):
        ckpt = _make_ckpt(tmp_path, seed=4)
        builder = load_player(
            {
                'type': 'cfr',
                'ckpt': ckpt,
                'n_simulations': 8,
            }
        )
        player = builder(seed=0)
        # MCTS wrapper also holds the CFRAgent
        assert isinstance(player.agent, CFRAgent)
        assert player.config.n_rollouts == 8

    def test_unknown_ckpt_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_player(
                {
                    'type': 'cfr',
                    'ckpt': str(tmp_path / 'missing.pt'),
                }
            )


# ------------------------------------------------------------------ #
# End-to-end: CFR argmax vs random via run_matchup


class TestCFRMatchup:
    def test_cfr_argmax_vs_random_completes(self, tmp_path):
        """CFR ckpt plays argmax against a random opponent. Game must
        reach terminal within max_game_steps, result must be a valid
        win-rate."""
        ckpt = _make_ckpt(tmp_path, seed=5)
        result = run_matchup(
            players=[
                {'type': 'cfr', 'ckpt': ckpt, 'n_simulations': 0},
                {'type': 'random'},
            ],
            mode='fixed',
            team_0=['赤蝶'],
            team_1=['墨客'],
            games_per_cell=1,
            max_game_steps=400,
            data_dir=DATA_DIR,
            seed=100,
        )
        assert result.aggregate.n_games == 2
        assert 0.0 <= result.aggregate.win_rate <= 1.0

    def test_cfr_argmax_vs_cfr_argmax_completes(self, tmp_path):
        """Two different CFR ckpts head-to-head. Exercises loader
        invocation for both player slots."""
        ckpt_a = _make_ckpt(tmp_path, seed=6)
        ckpt_b = _make_ckpt(tmp_path, seed=7)
        result = run_matchup(
            players=[
                {'type': 'cfr', 'ckpt': ckpt_a, 'n_simulations': 0},
                {'type': 'cfr', 'ckpt': ckpt_b, 'n_simulations': 0},
            ],
            mode='fixed',
            team_0=['赤蝶'],
            team_1=['墨客'],
            games_per_cell=1,
            max_game_steps=400,
            data_dir=DATA_DIR,
            seed=200,
        )
        assert result.aggregate.n_games == 2
