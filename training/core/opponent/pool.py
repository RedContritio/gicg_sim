"""OpponentPool — actor-side mixed opponent sampling.

Adapted from training/dmc/opponent_pool.py (paradigm-agnostic core
extracted). Holds a WeightedMix over registered opponent names + a
historical-ckpt ring buffer; paradigm provides a factory to build a
'historical' player from a state_dict.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Dict, Optional

from training.core.eval.baselines import OpponentRegistry
from training.core.opponent.mix import WeightedMix


HistoricalAgentFactory = Callable[[Any], Any]  # state_dict → Player


class OpponentPool:
    """Paradigm-agnostic opponent pool.

    Args:
        registry: OpponentRegistry with named opponents (random / F1-D2 ...)
        weights: dict {name: weight}; ``'historical'`` is a reserved
            name that routes to the ring buffer instead of the registry.
        ring_size: historical ckpt ring buffer size.
        historical_factory: ``state_dict → Player`` (paradigm-supplied;
            None → 'historical' falls back to random).
        seed: master seed.
    """

    HISTORICAL = 'historical'

    def __init__(
        self,
        registry: OpponentRegistry,
        weights: Dict[str, float],
        ring_size: int = 32,
        historical_factory: Optional[HistoricalAgentFactory] = None,
        seed: int = 0,
    ) -> None:
        if not weights:
            raise ValueError('OpponentPool: weights empty')
        # Verify non-historical entries exist in registry.
        unknown = [n for n in weights if n != self.HISTORICAL and n not in registry.names()]
        if unknown:
            raise ValueError(
                f'OpponentPool: weights references unknown opponent(s): {unknown} (known: {registry.names()})'
            )
        self.registry = registry
        self.weights = dict(weights)
        self._mix = WeightedMix(list(weights.keys()), list(weights.values()), seed=seed)
        self._ring: deque = deque(maxlen=ring_size)
        self.historical_factory = historical_factory
        self._seed_offset = 0
        self._master_seed = seed

    def add_snapshot(self, state_dict: Any) -> None:
        self._ring.append(state_dict)

    def sample(self, episode_seed: Optional[int] = None) -> Any:
        kind = self._mix.sample()
        seed = (episode_seed if episode_seed is not None else self._master_seed) + self._seed_offset
        self._seed_offset += 1
        if kind == self.HISTORICAL:
            if self._ring and self.historical_factory is not None:
                import random as _r

                sd = _r.Random(seed).choice(list(self._ring))
                return self.historical_factory(sd)
            # Cold start: fall back to random.
            return self.registry.get('random', seed=seed) if 'random' in self.registry.names() else None
        return self.registry.get(kind, seed=seed)

    def ring_size(self) -> int:
        return len(self._ring)
