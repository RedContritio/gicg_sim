"""In-process ring buffer with the shared-memory buffer API surface."""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from training.core.buffer.base import BufferBase
from training.core.protocols import Batch, CollectorOutput


class SHMRingBuffer(BufferBase):
    """In-process fallback for the multi-process producer API.

    Despite its name, this class currently stores entries in a process-local
    deque. The actor IPC package provides the actual shared-memory channels.
    """

    def __init__(self, capacity: int) -> None:
        super().__init__(capacity)
        self._buf: deque = deque(maxlen=capacity)

    def __len__(self) -> int:
        return len(self._buf)

    def push(self, batch: CollectorOutput) -> None:
        for t in batch.transitions:
            self._buf.append(t)

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        n = len(self._buf)
        if n < batch_size:
            raise ValueError(f'SHMRingBuffer.sample: have {n} < batch_size={batch_size}')
        rng = rng or np.random.default_rng()
        idx = rng.choice(n, size=batch_size, replace=False)
        data = [self._buf[int(i)] for i in idx]
        return Batch(data={'transitions': data}, weights=None, size=batch_size)

    def clear(self) -> None:
        self._buf.clear()

    def state_dict(self) -> dict:
        sd = super().state_dict()
        sd['entries'] = list(self._buf)
        return sd

    def load_state_dict(self, sd: dict) -> None:
        super().load_state_dict(sd)
        self._buf.clear()
        for e in sd.get('entries', [])[-self.capacity :]:
            self._buf.append(e)
