"""D2: PerOpponentPool tests."""

from __future__ import annotations

import random

import pytest

from training.paradigms.az.determinize import (
    PerOpponentPool,
    PublicObservation,
    SharedFixedPool,
)


def _obs(opponent=1):
    """Construct a valid-enough PublicObservation for sample dispatch."""
    return PublicObservation(
        viewing_player=1 - opponent,
        opponent=opponent,
        opponent_hand_size=3,
        opponent_deck_count=5,
        opponent_discard=[],
    )


def test_per_opponent_pool_dispatches_by_opponent():
    pool_by_player = {
        0: [10, 20, 30],
        1: [40, 50, 60],
    }
    spec = PerOpponentPool(pool_by_player)

    # Opponent=1 should get player 1's pool
    got = spec.sample_opponent_deck(random.Random(0), _obs(opponent=1))
    assert got == [40, 50, 60]

    # Opponent=0 should get player 0's pool
    got = spec.sample_opponent_deck(random.Random(0), _obs(opponent=0))
    assert got == [10, 20, 30]


def test_per_opponent_pool_returns_copy_not_alias():
    pool_by_player = {0: [1, 2, 3], 1: [4, 5, 6]}
    spec = PerOpponentPool(pool_by_player)
    got = spec.sample_opponent_deck(random.Random(0), _obs(opponent=1))
    got.append(99)  # mutate returned list
    # Internal state should not leak
    got2 = spec.sample_opponent_deck(random.Random(0), _obs(opponent=1))
    assert got2 == [4, 5, 6], "spec's internal pool got mutated via returned ref"


def test_per_opponent_pool_rejects_wrong_keys():
    with pytest.raises(ValueError, match='keys'):
        PerOpponentPool({0: [1, 2, 3]})  # missing key 1

    with pytest.raises(ValueError, match='keys'):
        PerOpponentPool({0: [1], 1: [2], 2: [3]})  # extra key 2


def test_shared_fixed_pool_ignores_opponent_key():
    """SharedFixedPool is opponent-agnostic — same pool regardless."""
    spec = SharedFixedPool([1, 2, 3])
    for opp in (0, 1):
        got = spec.sample_opponent_deck(random.Random(0), _obs(opponent=opp))
        assert got == [1, 2, 3]
