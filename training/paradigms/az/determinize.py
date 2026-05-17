"""Determinization sampler for IS-MCTS.

See docs/az/determinization.md for the full design. This module is the
Python side of the "sample a plausible hidden state per rollout" step.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np

from training.core.obs_constants import DICE_COLOR_COUNT


@dataclass
class PublicObservation:
    """The subset of the game state that the viewing player can
    legally see when determinizing."""

    viewing_player: int
    opponent: int
    opponent_hand_size: int
    opponent_deck_count: int
    opponent_discard: list[int]
    opponent_dice_paid: list[int] = field(default_factory=lambda: [0] * 8)
    opponent_dice_tuned_out: list[int] = field(default_factory=lambda: [0] * 8)


@dataclass
class HiddenState:
    """One sampled determinization."""

    opponent_hand: list[int]
    opponent_deck: list[int]
    opponent_dice_colors: np.ndarray | None = None


class CardPoolSpec(Protocol):
    """Describes the opponent's plausible deck pool."""

    def sample_opponent_deck(
        self,
        rng: random.Random,
        observations: 'PublicObservation',
    ) -> list[int]: ...


class SharedFixedPool:
    """MVP pool spec: both players share exactly the same fixed card pool."""

    def __init__(self, card_refs: Sequence[int]):
        self.card_refs = list(card_refs)

    def sample_opponent_deck(self, rng, observations: 'PublicObservation'):
        del rng, observations
        return list(self.card_refs)


class PerOpponentPool:
    """Per-opponent pool spec: each player has their own known deck
    composition, keyed by which player we're modeling the opponent as."""

    def __init__(self, pool_by_opponent: dict):
        if set(pool_by_opponent.keys()) != {0, 1}:
            raise ValueError(f'PerOpponentPool: need keys {{0, 1}}, got {sorted(pool_by_opponent.keys())}')
        self.pool_by_opponent = {
            0: list(pool_by_opponent[0]),
            1: list(pool_by_opponent[1]),
        }

    def sample_opponent_deck(self, rng, observations: 'PublicObservation'):
        del rng
        return list(self.pool_by_opponent[observations.opponent])


def sample_opponent_dice(
    rng: random.Random,
    total_count: int,
    paid_counts: list[int] | None = None,
    tuned_out_counts: list[int] | None = None,
    n_colors: int = DICE_COLOR_COUNT,
) -> np.ndarray:
    """Sample an opponent dice-color distribution under a Bayesian
    posterior given observed payments + tune-out events."""
    if total_count <= 0:
        return np.zeros(n_colors, dtype=np.int32)
    seed = rng.randint(0, 2**63 - 1)
    np_rng = np.random.default_rng(seed)

    alpha = np.ones(n_colors, dtype=np.float64)
    for evidence, label in [
        (paid_counts, 'paid_counts'),
        (tuned_out_counts, 'tuned_out_counts'),
    ]:
        if evidence is None:
            continue
        arr = np.asarray(evidence, dtype=np.float64)
        if arr.shape != (n_colors,):
            raise ValueError(f'{label} length {arr.shape} != n_colors {n_colors}')
        alpha = alpha + arr

    p = np_rng.dirichlet(alpha)
    draws = np_rng.multinomial(total_count, p)
    return draws.astype(np.int32)


def _subtract_public(pool: list[int], discard_refs: list[int]) -> list[int]:
    """Multiset-subtract publicly-committed cards from the pool."""
    remaining = list(pool)
    for ref in discard_refs:
        try:
            remaining.remove(ref)
        except ValueError:
            pass
    return remaining


def _build_public_observation(env, viewing_player: int) -> PublicObservation:
    """Read only the fields the viewing player is allowed to see."""
    if viewing_player not in (0, 1):
        raise ValueError(f'viewing_player must be 0 or 1, got {viewing_player}')
    opponent = 1 - viewing_player
    engine = env._engine
    return PublicObservation(
        viewing_player=viewing_player,
        opponent=opponent,
        opponent_hand_size=int(engine.hand_count(opponent)),
        opponent_deck_count=int(engine.deck_count(opponent)),
        opponent_discard=list(engine.discard_refs(opponent)),
        opponent_dice_paid=list(engine.dice_paid(opponent)),
        opponent_dice_tuned_out=list(engine.dice_tuned_out(opponent)),
    )


def sample_hidden_state(
    env,
    viewing_player: int,
    card_pool_spec: CardPoolSpec,
    rng: random.Random,
    opponent_dice_total: int | None = None,
) -> HiddenState:
    """Sample a concrete hidden state for IS-MCTS determinization."""
    pub = _build_public_observation(env, viewing_player)

    pool = card_pool_spec.sample_opponent_deck(rng, pub)

    remaining = _subtract_public(pool, pub.opponent_discard)

    hand_size = pub.opponent_hand_size
    deck_size = pub.opponent_deck_count
    needed = hand_size + deck_size

    if needed > len(remaining):
        needed = len(remaining)
        if hand_size > needed:
            hand_size = needed
            deck_size = 0
        else:
            deck_size = needed - hand_size

    chosen = rng.sample(remaining, needed)
    hand_refs = chosen[:hand_size]
    deck_refs = chosen[hand_size : hand_size + deck_size]
    rng.shuffle(deck_refs)

    dice_colors: np.ndarray | None = None
    if opponent_dice_total is not None:
        dice_colors = sample_opponent_dice(
            rng,
            opponent_dice_total,
            paid_counts=pub.opponent_dice_paid,
            tuned_out_counts=pub.opponent_dice_tuned_out,
        )

    return HiddenState(
        opponent_hand=hand_refs,
        opponent_deck=deck_refs,
        opponent_dice_colors=dice_colors,
    )


def apply_determinization(env, hidden: HiddenState, opponent: int) -> None:
    """Inject a sampled hidden state back into the engine."""
    env.set_player_hand(opponent, list(hidden.opponent_hand))
    env.set_player_deck(opponent, list(hidden.opponent_deck))
    if hidden.opponent_dice_colors is not None:
        env.set_player_dice(opponent, hidden.opponent_dice_colors.tolist())
