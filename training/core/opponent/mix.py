"""WeightedMix — pick name by weight (paradigm-agnostic).

Used by OpponentPool.sample() to choose 'random' vs 'F1-D2' vs
'historical' etc."""

from __future__ import annotations

import random
from typing import List


class WeightedMix:
    """Names + weights with weighted random.choice."""

    def __init__(self, names: List, weights: List, seed: int = 0) -> None:
        if len(names) != len(weights):
            raise ValueError(f'WeightedMix: len(names)={len(names)} != len(weights)={len(weights)}')
        if not names:
            raise ValueError('WeightedMix: names empty')
        if any(w < 0 for w in weights):
            raise ValueError(f'WeightedMix: negative weight in {weights}')
        if sum(weights) == 0:
            raise ValueError('WeightedMix: weights sum to 0')
        self.names = list(names)
        self.weights = list(weights)
        self._rng = random.Random(seed)

    def sample(self) -> str:
        return self._rng.choices(self.names, weights=self.weights, k=1)[0]

    def seed(self, s: int) -> None:
        self._rng.seed(s)
