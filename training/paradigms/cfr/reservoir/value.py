"""ValueBuffer — scalar episode outcome target for the value head."""

from __future__ import annotations

from typing import Any

import numpy as np

from training.paradigms.cfr.reservoir.base import CFRReservoirBase


class ValueBuffer(CFRReservoirBase):
    """Target: scalar episode outcome in {-1, 0, +1} from acting
    player's perspective."""

    TARGET_KEY = 'outcome'

    def _validate_target(self, target: Any) -> None:
        val = float(target)
        if not (-1.0 <= val <= 1.0):
            raise ValueError(f'ValueBuffer: outcome {val} outside [-1, 1]')

    def _coerce_target(self, target: Any) -> np.ndarray:
        return np.float32(target)

    def _stack_targets(self, entries: list[dict]) -> np.ndarray:
        return np.array(
            [e[self.TARGET_KEY] for e in entries],
            dtype=np.float32,
        )
