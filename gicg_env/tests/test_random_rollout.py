"""Correctness tests for the Go-side GicgEngine.random_rollout.

Guarantees:
- Given same starting state + same seed → same winner (deterministic)
- Different seeds → distribution over winners (no degenerate case)
- Terminal states on entry → returns immediately with existing winner
- Large max_steps → always reaches terminal (engine terminates games)
"""

from __future__ import annotations

from collections import Counter

import pytest

from gicg_env import GicgEnv


def _make_env(seed: int = 0) -> GicgEnv:
    env = GicgEnv(
        team_0=['赤蝶'],
        team_1=['墨客'],
        card_pool=None,
        seed=seed,
        data_dir='data',
    )
    env.reset(seed=seed)
    return env


def test_random_rollout_terminates():
    """A rollout with large max_steps from the initial state should
    always reach terminal (GICG games have bounded length)."""
    env = _make_env(seed=1)
    winner, n_steps = env._engine.random_rollout(seed=42, max_steps=400)
    assert winner in (0, 1, 2), f'non-terminal winner: {winner}'
    assert n_steps > 0
    assert n_steps <= 400


def test_random_rollout_deterministic_same_seed():
    """Same starting state + same seed → same winner + same n_steps."""
    env1 = _make_env(seed=1)
    env2 = _make_env(seed=1)  # identical starting state

    w1, n1 = env1._engine.random_rollout(seed=12345, max_steps=400)
    w2, n2 = env2._engine.random_rollout(seed=12345, max_steps=400)

    assert w1 == w2, f'same seed → different winner ({w1} vs {w2})'
    assert n1 == n2, f'same seed → different n_steps ({n1} vs {n2})'


def test_random_rollout_different_seeds_spread():
    """Different seeds should produce a distribution over winners
    (not all seeds give the same result from the same state)."""
    env_seed = 7
    winners = []
    for rollout_seed in range(20):
        env = _make_env(seed=env_seed)
        w, _ = env._engine.random_rollout(seed=rollout_seed * 1000 + 1, max_steps=400)
        winners.append(w)
    dist = Counter(winners)
    # At least 2 distinct winners (0 or 1 or 2), can't all be the same
    assert len(dist) >= 2, f'winner degenerate: {dist}'


def test_random_rollout_max_steps_cap():
    """max_steps=0 → no steps taken, winner is -1 (non-terminal)."""
    env = _make_env(seed=2)
    winner, n_steps = env._engine.random_rollout(seed=1, max_steps=0)
    assert n_steps == 0
    assert winner == -1  # sentinel: not terminal


def test_random_rollout_on_terminal_state():
    """If the engine is already terminal when entered, returns its
    existing winner immediately with n_steps=0."""
    env = _make_env(seed=3)
    # First drive it to terminal with a long rollout
    env._engine.random_rollout(seed=99, max_steps=400)
    assert env._engine.done

    # Now run another rollout — should be a no-op
    winner, n_steps = env._engine.random_rollout(seed=999, max_steps=400)
    assert n_steps == 0
    assert winner in (0, 1, 2)
    assert winner == env._engine.winner
