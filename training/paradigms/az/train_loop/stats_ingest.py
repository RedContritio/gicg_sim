"""Drain server_stats events from the inference server into metrics.jsonl.

Phase 2-ζ (FU-W4-AZ-rewrite, T2.ζ) — inlined from
``training.paradigms.az.legacy.train_loop.stats_ingest``.
"""

from __future__ import annotations

import queue as queue_mod
import threading


def stats_ingest_loop(stats_queue, log, stop_event: threading.Event) -> None:
    """Drain ``server_stats`` events from the inference server and
    forward them into ``metrics.jsonl`` via the shared logger."""
    while not stop_event.is_set():
        try:
            msg = stats_queue.get(timeout=0.25)
        except queue_mod.Empty:
            continue
        kind = msg.pop('kind', 'server_stats')
        log(kind, msg)
