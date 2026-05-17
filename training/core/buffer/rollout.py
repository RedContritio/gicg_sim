"""RolloutBuffer — on-policy buffer cleared every PPO iter.

Holds N rollout transitions; PPO trains for K epochs × minibatch
then ``clear()``. No eviction policy — capacity is hard cap."""

from __future__ import annotations

from typing import Optional

import numpy as np

from training.core.buffer.base import BufferBase
from training.core.protocols import Batch, CollectorOutput


class RolloutBuffer(BufferBase):
    """Plain list of transitions. ``push`` raises when over capacity
    (PPO never overflows by design — N rollouts == capacity)."""

    def __init__(self, capacity: int) -> None:
        super().__init__(capacity)
        self._entries: list = []

    def __len__(self) -> int:
        return len(self._entries)

    def push(self, batch: CollectorOutput) -> None:
        for t in batch.transitions:
            if len(self._entries) >= self.capacity:
                raise RuntimeError(f'RolloutBuffer.push: over capacity={self.capacity}; clear() between iters')
            self._entries.append(t)

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        if batch_size <= 0:
            raise ValueError(f'RolloutBuffer.sample: batch_size must be > 0,got {batch_size}')
        n = len(self._entries)
        if n < batch_size:
            raise ValueError(f'RolloutBuffer.sample: have {n} < batch_size={batch_size}')
        rng = rng or np.random.default_rng()
        idx = rng.choice(n, size=batch_size, replace=False)
        data = [self._entries[int(i)] for i in idx]
        return Batch(data={'transitions': data}, weights=None, size=batch_size)

    def clear(self) -> None:
        self._entries.clear()

    def state_dict(self) -> dict:
        sd = super().state_dict()
        sd['entries'] = list(self._entries)
        return sd

    def load_state_dict(self, sd: dict) -> None:
        super().load_state_dict(sd)
        self._entries = list(sd.get('entries', []))
