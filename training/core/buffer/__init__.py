"""training.core.buffer — paradigm-agnostic buffer primitives.

Adapted from training/framework/buffer/ + training/dmc/replay.py +
training/cfr/reservoir.py. Each subclass implements the ``Buffer``
Protocol (training/core/protocols.py).
"""

from training.core.buffer.base import BufferBase
from training.core.buffer.dataset import DatasetBuffer
from training.core.buffer.replay import ReplayBuffer
from training.core.buffer.reservoir import ReservoirBuffer
from training.core.buffer.rollout import RolloutBuffer
from training.core.buffer.static_dedup import StaticDedupBufferBase

__all__ = [
    'BufferBase',
    'DatasetBuffer',
    'ReplayBuffer',
    'ReservoirBuffer',
    'RolloutBuffer',
    'StaticDedupBufferBase',
]
