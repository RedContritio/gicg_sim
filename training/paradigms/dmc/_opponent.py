"""DMC adapter opponent pool — relocated from ``legacy/opponent_pool.py``.

Mixed opponent pool for DMC self-play training: random / F1-D2 / F1-D4
/ historical ckpt. Per decision #4 in
``training/paradigms/dmc/PLAN.md`` and original spec D4.

Each episode start, the trainer samples an opponent class according to
weights; ``historical`` draws from a ring buffer of recent learner ckpt
snapshots (cold-start falls back to random).

Note: ``legacy/eval/periodic_eval.py`` still imports ``RandomPlayer``
from ``legacy/opponent_pool.py`` — that file now re-exports from here
during the legacy retirement transition.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from training.core.matchup.greedy_player import GreedyPlayer

# A "player" is anything with select_action(env) -> int.
PlayerFactory = Callable[[], object]


@dataclass
class OpponentPoolConfig:
    """Mixed opponent pool for DMC self-play.

    Weights for each opponent class. Sampled per episode at start.
    Default 30/30/10/30 = random / F1-D2 / F1-D4 / historical.
    ``ring_size`` = how many recent ckpts to keep in historical ring.
    """

    random: float = 0.30
    f1d2: float = 0.30
    f1d4: float = 0.10
    historical: float = 0.30
    ring_size: int = 20

    def __post_init__(self):
        s = self.random + self.f1d2 + self.f1d4 + self.historical
        if abs(s - 1.0) > 1e-6:
            raise ValueError(
                f'OpponentPoolConfig: weights must sum to 1.0, got {s} '
                f'(random={self.random} f1d2={self.f1d2} f1d4={self.f1d4} hist={self.historical})'
            )


class RandomPlayer:
    """Uniform random over legal actions; ``select_action(env) -> int``."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def select_action(self, env) -> int:
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            return 0
        return self.rng.randrange(len(kinds))


class OpponentPool:
    """Random / F1-D2 / F1-D4 / historical sampler."""

    def __init__(
        self,
        cfg: OpponentPoolConfig,
        dmc_agent_factory: Optional[PlayerFactory] = None,
        seed: int = 0,
    ):
        """
        Args:
            cfg: OpponentPoolConfig with the 4 weights + ring_size.
            dmc_agent_factory: callable that builds a DMC agent loaded
                from a given state_dict (used for historical). If None,
                historical samples fall back to random.
            seed: RNG seed; ``__init__`` 强制传入避免未来 path 忘 seed 时
                sample 不可复现。后续 ``.seed()`` 仍可覆盖。
        """
        self.cfg = cfg
        self.dmc_agent_factory = dmc_agent_factory
        self._ring: deque = deque(maxlen=cfg.ring_size)
        self._rng = random.Random(seed)

    def seed(self, seed: int) -> None:
        self._rng.seed(seed)

    def add_snapshot(self, state_dict) -> None:
        """Add a learner ckpt snapshot to historical ring."""
        self._ring.append(state_dict)

    def sample(self):
        """Return a player instance for one episode."""
        kind = self._weighted_choice()
        return self._build_player(kind)

    def _weighted_choice(self) -> str:
        weights = (self.cfg.random, self.cfg.f1d2, self.cfg.f1d4, self.cfg.historical)
        kinds = ('random', 'F1-D2', 'F1-D4', 'historical')
        return self._rng.choices(kinds, weights=weights, k=1)[0]

    def _build_player(self, kind: str):
        if kind == 'random':
            return RandomPlayer(seed=self._rng.randint(0, 2**31 - 1))
        if kind == 'F1-D2':
            return GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=self._rng.randint(0, 2**31 - 1))
        if kind == 'F1-D4':
            return GreedyPlayer(features='F1', depth=4, dice_greedy=True, seed=self._rng.randint(0, 2**31 - 1))
        if kind == 'historical':
            if self._ring and self.dmc_agent_factory is not None:
                state_dict = self._rng.choice(self._ring)
                return self.dmc_agent_factory(state_dict)
            return RandomPlayer(seed=self._rng.randint(0, 2**31 - 1))
        raise ValueError(f'unknown opponent kind: {kind}')
