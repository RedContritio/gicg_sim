"""CFR reservoir buffers: Advantage / Strategy / Value.

Concrete reservoir classes inherit from ``CFRReservoirBase`` which
adds Vitter-R sampling + CFR-specific dynamic key validation on top
of the framework's ``StaticDedupBufferBase``.
"""

from __future__ import annotations

from training.paradigms.cfr.reservoir.advantage import AdvantageBuffer
from training.paradigms.cfr.reservoir.base import (
    CFRReservoirBase,
    SAMPLE_DYNAMIC_KEYS,
)
from training.paradigms.cfr.reservoir.strategy import StrategyBuffer
from training.paradigms.cfr.reservoir.value import ValueBuffer
from training.core.buffer.static_dedup import GAME_STATIC_KEYS

__all__ = [
    'AdvantageBuffer',
    'CFRReservoirBase',
    'GAME_STATIC_KEYS',
    'SAMPLE_DYNAMIC_KEYS',
    'StrategyBuffer',
    'ValueBuffer',
]
