"""DatasetBuffer — in-memory full dataset for BC.

No eviction — all examples held forever. Sample is uniform random.

Sample contract:
- If ``batch_builder`` provided at init (BC driver path): sample returns
  ``Batch(data={'fields': batch_builder(indices)})`` — collector calls
  BCDataset.build_batch via collector.build_batch shim to reconstruct
  the full obs dict (legal_mask / chosen_action / tied_mask / terminal_z
  + obs tensors). This is what BCLoss.compute expects.
- If no ``batch_builder`` (generic path): sample returns
  ``Batch(data={'transitions': [Transition, ...]})`` — caller-side
  reconstruction.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import numpy as np

from training.core.buffer.base import BufferBase
from training.core.protocols import Batch, CollectorOutput


class DatasetBuffer(BufferBase):
    """Full-dataset buffer for behavior cloning. ``push`` extends the
    backing list without bound; ``capacity`` is treated as a soft cap
    (raises if exceeded — BC dataset should be pre-known size)."""

    def __init__(
        self,
        capacity: int,
        batch_builder: Optional[Callable[[np.ndarray], dict]] = None,
    ) -> None:
        super().__init__(capacity)
        self._entries: list = []
        # If set, sample() returns data={'fields': batch_builder(indices)}
        # (BC driver path so BCLoss.compute can read batch.data['fields']).
        # Otherwise sample() returns data={'transitions': [...]}.
        self._batch_builder = batch_builder

    def __len__(self) -> int:
        return len(self._entries)

    def push(self, batch: CollectorOutput) -> None:
        for t in batch.transitions:
            if len(self._entries) >= self.capacity:
                raise RuntimeError(
                    f'DatasetBuffer.push: over capacity={self.capacity} (BC dataset should be sized exact)'
                )
            self._entries.append(t)

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        if batch_size <= 0:
            raise ValueError(f'DatasetBuffer.sample: batch_size must be > 0,got {batch_size}')
        n = len(self._entries)
        if n < batch_size:
            raise ValueError(f'DatasetBuffer.sample: have {n} < batch_size={batch_size}')
        rng = rng or np.random.default_rng()
        idx = rng.choice(n, size=batch_size, replace=False)

        if self._batch_builder is not None:
            # BC driver path — rebuild full obs dict from dataset indices
            # via collector.build_batch (delegates to BCDataset.build_batch).
            # The Transition.payload['dataset_idx'] field carries the
            # original dataset row index; we extract it for the builder.
            dataset_indices = self._extract_dataset_indices(idx)
            fields = self._batch_builder(dataset_indices)
            return Batch(data={'fields': fields}, weights=None, size=batch_size)

        # Generic path: caller-side reconstruction.
        data = [self._entries[int(i)] for i in idx]
        return Batch(data={'transitions': data}, weights=None, size=batch_size)

    def _extract_dataset_indices(self, idx: np.ndarray) -> np.ndarray:
        """Map sampled buffer-position indices → dataset row indices.

        BC's DatasetCollector emits one Transition per dataset decision
        with ``payload={'dataset_idx': i, ...}``. We honor that mapping
        rather than assuming buffer-position == dataset-idx (the latter
        is true in practice but fragile if shuffle is added).
        """
        out = np.empty(len(idx), dtype=np.int64)
        for k, i in enumerate(idx):
            t: Any = self._entries[int(i)]
            payload = getattr(t, 'payload', None) or {}
            ds_idx = payload.get('dataset_idx')
            if ds_idx is None:
                # Fallback: assume buffer position == dataset index
                # (BC DatasetCollector preserves order).
                ds_idx = int(i)
            out[k] = int(ds_idx)
        return out

    def clear(self) -> None:
        self._entries.clear()

    def state_dict(self) -> dict:
        sd = super().state_dict()
        sd['entries'] = list(self._entries)
        return sd

    def load_state_dict(self, sd: dict) -> None:
        super().load_state_dict(sd)
        self._entries = list(sd.get('entries', []))
