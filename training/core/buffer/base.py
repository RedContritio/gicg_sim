"""Buffer base class — common state_dict / load_state_dict / len skeleton.

Subclasses implement push / sample / clear. Protocol spec lives in
``training/core/protocols.py``."""

from __future__ import annotations

from typing import Optional

import numpy as np

from training.core.protocols import Batch, CollectorOutput


class BufferBase:
    """Minimal shared base. Owns capacity + a default state_dict that
    serializes capacity + size only (subclass extends for entries)."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError(f'BufferBase: capacity must be > 0,got {capacity}')
        self.capacity = capacity

    def __len__(self) -> int:  # noqa: D401 — Protocol contract
        raise NotImplementedError

    def push(self, batch: CollectorOutput) -> None:
        raise NotImplementedError

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def state_dict(self) -> dict:
        return {'capacity': self.capacity, 'size': len(self)}

    def load_state_dict(self, sd: dict) -> None:
        if sd.get('capacity') != self.capacity:
            raise ValueError(
                f'BufferBase.load_state_dict: capacity mismatch sd={sd.get("capacity")} vs self={self.capacity}'
            )
