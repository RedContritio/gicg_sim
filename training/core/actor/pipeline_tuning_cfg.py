"""Runtime tuning for the DMC Go subprocess collector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PipelineTuningCfg:
    """SHM, inference, lifecycle, polling, and Go runtime controls.

    The dataclass is frozen because collectors and subprocess launchers read
    it as an immutable bundle. ``inf_max_batch=None`` resolves to the actor
    count in ``spawn_pipeline``.
    """

    # Each slot must hold one encoded episode batch. Producers retry when
    # the ring is full, and backpressure is reported in training metrics.
    shm_capacity: int = 32
    shm_slot_size: int = 4 * 1024 * 1024

    # Inference batches flush when full or after the timeout.
    inf_max_batch: Optional[int] = None
    inf_batch_timeout_ms: int = 2

    # Subprocess readiness and socket I/O deadlines.
    ready_timeout_s: float = 30.0
    io_timeout_ms: int = 30_000

    # Maximum collection wall time and SHM polling interval.
    collect_deadline_s: float = 60.0
    poll_interval_s: float = 0.005

    # ``None`` derives the inference device from network parameters.
    device: Optional[str] = None
    # Each subprocess normally hosts one actor, so one Go scheduler thread
    # avoids oversubscribing the host when many actors run.
    go_gomaxprocs: int = 1

    # Soft Go memory limit per actor process in MiB; zero means unbounded.
    go_mem_limit_mb: int = 1024
