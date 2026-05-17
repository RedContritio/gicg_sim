"""AdvantageBuffer — per-action regret vector target."""

from __future__ import annotations

from typing import Any

import numpy as np

from training.paradigms.cfr.reservoir.base import CFRReservoirBase


class AdvantageBuffer(CFRReservoirBase):
    """Target: per-action regret vector (max_actions,) float32.
    Trains the AdvantageNet that regret-matching samples actions from."""

    TARGET_KEY = 'regret'

    def __init__(self, capacity: int, max_actions: int):
        super().__init__(capacity)
        self.max_actions = max_actions

    def _validate_target(self, target: Any) -> None:
        arr = np.asarray(target)
        if arr.shape != (self.max_actions,):
            raise ValueError(f'AdvantageBuffer: target shape {arr.shape} != ({self.max_actions},)')

    def _coerce_target(self, target: Any) -> np.ndarray:
        return np.asarray(target, dtype=np.float32)

    def _stack_targets(self, entries: list[dict]) -> np.ndarray:
        return np.stack([e[self.TARGET_KEY] for e in entries]).astype(
            np.float32,
            copy=False,
        )
