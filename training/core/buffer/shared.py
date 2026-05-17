"""SHMRingBuffer — multi-process shared-memory ring (skeleton).

Async-mode buffer where actor processes write transitions directly
into shared memory + learner samples. Full implementation deferred to
P3-B per design (DMC adapter needs it); P3-A ships the contract +
in-process fallback so the protocol is exercised.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from training.core.buffer.base import BufferBase
from training.core.protocols import Batch, CollectorOutput


class SHMRingBuffer(BufferBase):
    """In-process ring buffer with the SHM API surface. P3-B replaces
    backing storage with multiprocessing.shared_memory + faster-fifo
    while keeping push/sample/clear/state_dict signatures.

    Distinction from ReplayBuffer: SHMRingBuffer is intended for
    multi-process producer → single-process consumer (the learner)."""

    def __init__(self, capacity: int) -> None:
        super().__init__(capacity)
        self._buf: deque = deque(maxlen=capacity)
        # TODO(P3-B): allocate shared_memory blocks + ipc/ring.py
        # backed circular pointer here.

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
