"""training.core.opponent — opponent pool (mixed strategy) primitives."""

from training.core.opponent.mix import WeightedMix
from training.core.opponent.pool import OpponentPool

__all__ = ['OpponentPool', 'WeightedMix']
