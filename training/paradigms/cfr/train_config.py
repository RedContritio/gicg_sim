"""CFR training config.

Reuses ``TrainingConfig`` for shared fields; CFR-specific iteration /
buffer / fit knobs live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from training.paradigms.cfr.traversal.config import TraversalConfig
from training.core.config.legacy import TrainingConfig


@dataclass
class CFRConfig(TrainingConfig):
    """Top-level CFR training config. Currently mirrors
    ``CFRTrainConfig`` for API compatibility — the dataclass split
    exists so future CFR-specific shared fields land here rather than
    adding to the framework base."""

    n_iterations: int = 100
    traversals_per_iteration: int = 64
    traverser_alternation: str = 'alternate'

    advantage_fit_steps_per_iter: int = 32
    advantage_lr: float = 1e-3
    advantage_reset_each_iter: bool = False

    strategy_fit_every: int = 4
    strategy_fit_steps: int = 64
    strategy_lr: float = 1e-3
    value_loss_alpha: float = 1.0

    grad_clip_max_norm: float = 1.0

    advantage_buffer_capacity: int = 100_000
    strategy_buffer_capacity: int = 200_000
    value_buffer_capacity: int = 100_000

    fit_batch_size: int = 128

    checkpoint_every: int = 10
    checkpoint_dir: Optional[str] = None

    traversal: TraversalConfig = field(default_factory=TraversalConfig)
