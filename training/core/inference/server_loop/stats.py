"""Emit inference throughput counters and batch-size percentiles."""

from __future__ import annotations

import multiprocessing as mp
import queue as queue_mod
import time


def _flush_stats(stats_queue: 'mp.Queue', state, force: bool) -> None:
    """Always-emit variant used on shutdown so no batch stats are lost."""
    now = time.perf_counter()
    if force or state.batches_since_emit > 0:
        _push_stats_event(stats_queue, state, now)


def _maybe_emit_stats(
    stats_queue: 'mp.Queue',
    state,
    interval_s: float,
) -> None:
    now = time.perf_counter()
    if now - state.last_emit_t < interval_s:
        return
    _push_stats_event(stats_queue, state, now)


def _push_stats_event(
    stats_queue: 'mp.Queue',
    state,
    now: float,
) -> None:
    dt = max(1e-6, now - state.last_emit_t)
    sizes = state.eval_batch_sizes
    if sizes:
        sorted_sizes = sorted(sizes)
        n = len(sorted_sizes)
        p50 = sorted_sizes[n // 2]
        p95 = sorted_sizes[min(n - 1, int(n * 0.95))]
        batch_mean = sum(sorted_sizes) / n
        batch_max = sorted_sizes[-1]
    else:
        p50 = p95 = batch_mean = batch_max = 0
    try:
        stats_queue.put(
            {
                'kind': 'server_stats',
                'interval_s': round(dt, 3),
                'batches': state.batches_since_emit,
                'reqs': state.reqs_since_emit,
                'eval_batches': state.eval_batches_since_emit,
                'eval_reqs': state.eval_reqs_since_emit,
                'batch_mean': round(batch_mean, 2),
                'batch_p50': int(p50),
                'batch_p95': int(p95),
                'batch_max': int(batch_max),
                'reqs_per_s': round(state.reqs_since_emit / dt, 1),
                'weight_version': state.weight_version,
            },
            block=False,
        )
    except queue_mod.Full:
        pass
    state.batches_since_emit = 0
    state.reqs_since_emit = 0
    state.eval_batches_since_emit = 0
    state.eval_reqs_since_emit = 0
    state.eval_batch_sizes = []
    state.last_emit_t = now
