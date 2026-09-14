"""Shared base for legacy-style DMC and CFR run configurations.

The unified TOML pipeline uses ``training.core.config.base.TrainingConfig``;
older DMC and CFR entry points retain this smaller mutable dataclass.
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
