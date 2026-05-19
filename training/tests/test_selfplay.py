"""Integration tests for training/selfplay.py — the per-game
self-play loop that feeds the replay buffer.

Uses a real GicgEnv and a small random-init Agent. The MCTS rollout
count is kept low so tests stay under a couple seconds."""

from __future__ import annotations

import os
import random

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.paradigms.az.buffer import STEP_DYNAMIC_KEYS
from training.paradigms.az.determinize import SharedFixedPool
from training.paradigms.az.mcts import MCTSConfig
from training.paradigms.az.network import Agent, AgentConfig
from training.paradigms.az.selfplay import SelfPlayResult, play_self_game

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

# Shape constants matching the bundled DSL.
N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
N_HOOKS = 900
MAX_TOK = 64
MAX_ACTIONS = 512
D_MODEL = 16


def _make_agent(seed: int = 0) -> Agent:
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


def _make_env(seed: int = 0) -> GicgEnv:
    # ADR-0011: explicit deck_padding pins the legacy 15-slot 碌碌无为
    # shape so the legal-action count stays under MAX_ACTIONS=512. With
    # no padding the v_legacy pool produces a deck big enough that some
    # turns generate 500+ legal action vectors.
    env = GicgEnv(
        ['赤蝶'],
        ['赤蝶'],
        seed=seed,
        data_dir=DATA_DIR,
        deck_padding={'card': '碌碌无为', 'target_size': 15},
    )
    env.reset(seed=seed)
    return env


def _pool_refs(env: GicgEnv) -> list[int]:
    view = env.export_view()
    hand = view['players'][0]['hand']
    deck = view['players'][0]['deck_count']
    if not hand:
        return []
    filler = hand[0]['ref']
    return [c['ref'] for c in hand] + [filler] * deck


class TestPlaySelfGame:
    def test_returns_result_with_trajectory(self):
        env = _make_env(seed=7)
        try:
            agent = _make_agent()
            pool = _pool_refs(env)
            cfg = MCTSConfig(n_rollouts=10, max_rollout_depth=400)
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
            assert result.discovery_count >= 0
        finally:
            env.close()

    def test_game_static_has_all_keys(self):
        env = _make_env(seed=11)
        try:
            agent = _make_agent()
            pool = _pool_refs(env)
            cfg = MCTSConfig(n_rollouts=5, max_rollout_depth=400)
            result = play_self_game(
                agent,
                env,
                SharedFixedPool(pool),
                random.Random(0),
                mcts_config=cfg,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
            for key in ('hook_types', 'hook_values', 'hook_mask', 'counter_sids'):
                assert key in result.game_static
            # (n_active_hooks, max_tokens)
            assert result.game_static['hook_types'].ndim == 2
            assert result.game_static['hook_values'].shape == result.game_static['hook_types'].shape
            assert result.game_static['hook_mask'].ndim == 1
            assert result.game_static['counter_sids'].ndim == 1
        finally:
            env.close()

    def test_steps_have_all_dynamic_keys(self):
        env = _make_env(seed=13)
        try:
            agent = _make_agent()
            pool = _pool_refs(env)
            cfg = MCTSConfig(n_rollouts=5, max_rollout_depth=400)
            result = play_self_game(
                agent,
                env,
                SharedFixedPool(pool),
                random.Random(0),
                mcts_config=cfg,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
            assert len(result.steps) > 0
            for step in result.steps:
                missing = set(STEP_DYNAMIC_KEYS) - set(step.keys())
                assert not missing, f'step missing keys: {missing}'
                # _acting_player must have been stripped
                assert '_acting_player' not in step
        finally:
            env.close()

    def test_pi_target_sums_to_one_on_legal(self):
        env = _make_env(seed=17)
        try:
            agent = _make_agent()
            pool = _pool_refs(env)
            cfg = MCTSConfig(n_rollouts=10, max_rollout_depth=400)
            result = play_self_game(
                agent,
                env,
                SharedFixedPool(pool),
                random.Random(0),
                mcts_config=cfg,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
            for step in result.steps:
                pi = step['pi_target']
                legal = step['legal_mask']
                # pi is zero on illegal slots
                assert (pi[~legal] == 0).all()
                # pi sums to ~1 on legal slots
                s = pi[legal].sum()
                assert abs(s - 1.0) < 1e-5, f'pi sum on legal: {s}'
        finally:
            env.close()

    def test_z_target_perspective_flip(self):
        """For a terminal game, each step's z_target must match the
        acting player's own win/loss viewpoint:
          - If P0 won (engine winner = 0), P0-acted steps have z=+1,
            P1-acted steps have z=-1.
          - If P1 won (engine winner = 1), it's the mirror.
          - Draw: z=0 everywhere."""
        env = _make_env(seed=23)
        try:
            agent = _make_agent()
            pool = _pool_refs(env)
            cfg = MCTSConfig(n_rollouts=10, max_rollout_depth=400)
            result = play_self_game(
                agent,
                env,
                SharedFixedPool(pool),
                random.Random(0),
                mcts_config=cfg,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
            winner = result.winner
            # steps don't carry acting_player any more (stripped).
            # We can only check: the set of z_target values should
            # be a subset of {-1, 0, +1} and if winner is decisive
            # (0 or 1), every step has |z|=1.
            z_vals = np.array([s['z_target'] for s in result.steps])
            assert set(np.unique(z_vals)).issubset({-1.0, 0.0, 1.0})
            if winner in (0, 1):
                assert (np.abs(z_vals) == 1.0).all(), f'decisive winner={winner} but some z are 0: {z_vals}'
                # And z_vals should have BOTH signs because both
                # players acted (unless the game ended in the very
                # first move, which it shouldn't for GICG).
                if len(result.steps) >= 2:
                    assert set(z_vals) == {1.0, -1.0}, f'expected both +1 and -1 in z_target, got {set(z_vals)}'
        finally:
            env.close()


class TestFeedsBuffer:
    def test_result_plugs_into_buffer(self):
        """End-to-end: run one self-play game, hand the result to the
        replay buffer, sample from buffer. Shapes and keys must line
        up without any glue code."""
        from training.paradigms.az.buffer import ReplayBuffer

        env = _make_env(seed=29)
        try:
            agent = _make_agent()
            pool = _pool_refs(env)
            cfg = MCTSConfig(n_rollouts=8, max_rollout_depth=400)
            result = play_self_game(
                agent,
                env,
                SharedFixedPool(pool),
                random.Random(0),
                mcts_config=cfg,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
        finally:
            env.close()

        rb = ReplayBuffer(capacity=1000)
        rb.add_trajectory(result.game_static, result.steps)
        assert len(rb) == result.n_steps
        assert rb.n_games() == 1

        batch = rb.sample(min(4, result.n_steps), random.Random(0))
        assert batch['counter_values'].shape[0] > 0
        # Every key needed by forward_batch + az_losses
        for k in (
            'counter_values',
            'counter_sids',
            'hook_types',
            'hook_values',
            'hook_mask',
            'card_buckets',
            'enemy_sizes',
            'meta',
            'action_refs',
            'action_payments',
            'legal_mask',
            'pi_target',
            'z_target',
        ):
            assert k in batch, f'batch missing key {k}'
