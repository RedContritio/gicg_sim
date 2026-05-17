"""ReservoirBuffer — Vitter-R reservoir sampling.

Used by CFR (advantage / strategy reservoirs). Each entry has
equal long-run probability of inclusion regardless of arrival order."""

from __future__ import annotations

from typing import Optional

import numpy as np

from training.core.buffer.base import BufferBase
from training.core.protocols import Batch, CollectorOutput


class ReservoirBuffer(BufferBase):
    """Algorithm R reservoir. ``n_seen`` counts arrivals; each new entry
    after capacity has p=capacity/n_seen of replacing a random slot."""

    def __init__(self, capacity: int) -> None:
        super().__init__(capacity)
        self._entries: list = []
        self._n_seen: int = 0
        self._rng = np.random.default_rng()

    def __len__(self) -> int:
        return len(self._entries)

    def push(self, batch: CollectorOutput) -> None:
        for t in batch.transitions:
            self._n_seen += 1
            if len(self._entries) < self.capacity:
                self._entries.append(t)
            else:
                j = int(self._rng.integers(0, self._n_seen))
                if j < self.capacity:
                    self._entries[j] = t

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        if batch_size <= 0:
            raise ValueError(f'ReservoirBuffer.sample: batch_size must be > 0,got {batch_size}')
        n = len(self._entries)
        if n < batch_size:
            raise ValueError(f'ReservoirBuffer.sample: have {n} entries < batch_size={batch_size}')
        rng = rng or np.random.default_rng()
        idx = rng.choice(n, size=batch_size, replace=False)
        data = [self._entries[int(i)] for i in idx]
        return Batch(data={'transitions': data}, weights=None, size=batch_size)

    def clear(self) -> None:
        self._entries.clear()
        self._n_seen = 0

    def state_dict(self) -> dict:
        sd = super().state_dict()
        sd.update(entries=list(self._entries), n_seen=self._n_seen)
        return sd

    def load_state_dict(self, sd: dict) -> None:
        super().load_state_dict(sd)
        self._entries = list(sd.get('entries', []))
        self._n_seen = int(sd.get('n_seen', 0))
