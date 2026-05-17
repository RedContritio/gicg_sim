"""Abstract base for training run configs.

``training.az.config.AZConfig`` and ``training.cfr.config.CFRConfig``
inherit from this to share seed / n_workers / buffer_cap / artifacts_root
/ run_label / batch_size without leaking algorithm-specific knobs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrainingConfig:
    """Fields every training run needs regardless of algorithm."""

    seed: int = 42
    n_workers: int = 1
    buffer_cap: int = 50_000
    artifacts_root: str = 'artifacts'
    run_label: str = 'run'
    batch_size: int = 64
