"""Smoke tests for the Go-backed MCTS search (training/mcts_go.py).

These drive the Go MCTS end-to-end through the cgo entry point with a
real engine + small-d_model Agent, verifying:
  - MCTSSearch succeeds (rc == 0)
  - Returned visits sum to n_rollouts (no leaks)
  - Chosen action is a valid legal action index at the root state
  - Return shape matches the Python mcts_search reference

Full parity (visit-count equality vs Python) is out of scope here
— it requires bit-identical determinization sampling and rollout
seeding across backends. That lives in Step 5 of the Go MCTS
migration (see docs/2_decisions/adr-0004-is_mcts_migration.md)."""

import os
import random

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.paradigms.az.determinize import SharedFixedPool
from training.paradigms.az.mcts import MCTSConfig
from training.paradigms.az.mcts_go import mcts_search_go
from training.paradigms.az.network import Agent, AgentConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

OBS_MAX_CHARS = 6
OBS_CHAR_SLOTS = 128
OBS_PLAYER_SLOTS = 140
OBS_GLOBAL_SLOTS = 16
N_COUNTER_SLOTS = 2 * OBS_MAX_CHARS * OBS_CHAR_SLOTS + 2 * OBS_PLAYER_SLOTS + OBS_GLOBAL_SLOTS
N_HOOKS = 900
MAX_TOKENS = 120
MAX_ACTIONS = 1024


def _advance_past_select_active(env):
    while env._engine.phase == 1:
        env.step(0)
        if env.done:
            break


def _small_agent(env, seed=0):
    torch.manual_seed(seed)
    cfg = AgentConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=N_HOOKS,
        max_ops_per_hook=MAX_TOKENS,
        max_actions=MAX_ACTIONS,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )
    agent = Agent(cfg)
    agent.net.eval()
    agent.encode_static(env.static_obs)
    return agent


def _make_env(team_0, team_1, seed=42):
    env = GicgEnv(team_0, team_1, seed=seed, data_dir=DATA_DIR)
    env.reset(seed=seed)
    _advance_past_select_active(env)
    return env


def _pool_from_env(env, player=0):
    view = env.export_view()
    hand = view['players'][player]['hand']
    deck = view['players'][player]['deck_count']
    if not hand:
        return []
    filler = hand[0]['ref']
    return [c['ref'] for c in hand] + [filler] * deck


class TestMCTSGoBasic:
    def test_runs_and_returns_legal_action(self):
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            cfg = MCTSConfig(
                n_rollouts=20,
                max_rollout_depth=80,
                dirichlet_eps=0.0,  # avoid Dirichlet for determinism
                value_mix_lambda=1.0,  # skip random rollout for speed
                prior_mix_lambda=1.0,
                profile=False,
            )
            kinds, _ = env.get_legal_actions()
            n_legal = len(kinds)
            chosen, info = mcts_search_go(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg,
            )
            assert 0 <= chosen < n_legal, f'chosen={chosen} out of [0,{n_legal})'
            assert 'visits' in info
            assert 'pi' in info
            assert 'legal_ids' in info
            assert len(info['legal_ids']) == n_legal
            # Total visits == n_rollouts (no leaks from VL/panic).
            total_visits = sum(info['visits'].values())
            assert total_visits == cfg.n_rollouts, f'total visits {total_visits} != n_rollouts {cfg.n_rollouts}'
        finally:
            env.close()

    def test_parallel_rollouts(self):
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            cfg = MCTSConfig(
                n_rollouts=32,
                max_rollout_depth=80,
                parallel_rollouts=4,
                dirichlet_eps=0.0,
                value_mix_lambda=1.0,
                prior_mix_lambda=1.0,
                profile=False,
            )
            chosen, info = mcts_search_go(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg,
            )
            total_visits = sum(info['visits'].values())
            assert total_visits == cfg.n_rollouts
            assert 0 <= chosen < len(info['legal_ids'])
        finally:
            env.close()

    def test_value_mix_lambda_runs(self):
        """With λ<1 the leaf mixes net value + random rollout — exercises
        the in-Go GameRandomRollout path."""
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            cfg = MCTSConfig(
                n_rollouts=16,
                max_rollout_depth=80,
                dirichlet_eps=0.0,
                value_mix_lambda=0.5,
                prior_mix_lambda=1.0,
                profile=False,
            )
            chosen, info = mcts_search_go(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg,
            )
            total_visits = sum(info['visits'].values())
            assert total_visits == cfg.n_rollouts
            assert -1.0 <= info['root_value_p0'] <= 1.0
        finally:
            env.close()

    def test_selfplay_end_to_end(self):
        """play_self_game with backend='go' routes into mcts_search_go
        for every decision. Verifies the backend-routing branch in
        selfplay.py and catches integration breakage."""
        from training.paradigms.az.buffer import STEP_DYNAMIC_KEYS
        from training.paradigms.az.selfplay import play_self_game, SelfPlayResult

        env = _make_env(['赤蝶'], ['赤蝶'], seed=23)
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 0)
            cfg = MCTSConfig(
                n_rollouts=8,
                max_rollout_depth=400,
                dirichlet_eps=0.0,
                value_mix_lambda=1.0,
                prior_mix_lambda=1.0,
                profile=False,
                backend='go',
            )
            result = play_self_game(
                agent,
                env,
                SharedFixedPool(pool),
                random.Random(0),
                mcts_config=cfg,
                max_game_steps=400,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
            assert isinstance(result, SelfPlayResult)
            assert result.n_steps > 0
            assert result.winner in (0, 1, 2)
            for step in result.steps:
                missing = set(STEP_DYNAMIC_KEYS) - set(step.keys())
                assert not missing
        finally:
            env.close()

    def test_profile_emitted(self):
        env = _make_env(['赤蝶'], ['赤蝶'])
        try:
            agent = _small_agent(env)
            pool = _pool_from_env(env, 1)
            cfg = MCTSConfig(
                n_rollouts=12,
                max_rollout_depth=80,
                dirichlet_eps=0.0,
                value_mix_lambda=1.0,
                prior_mix_lambda=1.0,
                profile=True,
            )
            _, info = mcts_search_go(
                env,
                agent,
                SharedFixedPool(pool),
                random.Random(0),
                viewing_player=env.acting_player,
                config=cfg,
            )
            assert 'profile' in info
            prof = info['profile']
            assert prof['n_rollouts'] == cfg.n_rollouts
            assert prof['n_eval'] > 0
        finally:
            env.close()
