"""Paradigm-agnostic perf trace — zero overhead when disabled.

Activation: set ``PERF_TRACE=1`` in the parent process *before* any of
the involved processes (pipeline / actor / inference server) starts.
Module-level ``_ENABLED`` is sampled once at import time so the hot path
collapses to a single attribute load + branch when off.

API:

    from training.core.perf import trace
    trace.configure(role='actor', id=0)        # idempotent per process
    with trace.span('env.step'):
        env.step(action)
    trace.close()                              # flush + close handle

When ``PERF_TRACE`` is unset, ``span(...)`` returns a shared no-op
context manager (allocated once at import) and ``configure`` / ``close``
are no-ops — no file handles, no dict allocations, no perf_counter
calls.

Output: ``artifacts/_perf_logs/<role>_<id>.jsonl`` (path overridable via
``PERF_TRACE_DIR``). Each line aggregates ``_FLUSH_WINDOW`` events into
one JSON row with mean/p50/p95/max/sum/n per stage. Window flushes also
fire on a ``_FLUSH_INTERVAL_S`` wall timer so low-rate stages still land
on disk.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Optional

_ENABLED = os.getenv('PERF_TRACE') == '1'
_FLUSH_WINDOW = int(os.getenv('PERF_TRACE_FLUSH_N', '200'))
_FLUSH_INTERVAL_S = float(os.getenv('PERF_TRACE_FLUSH_S', '1.0'))


class _Noop:
    """Shared zero-alloc context manager for disabled paths."""

    __slots__ = ()

    def __enter__(self) -> '_Noop':
        return self

    def __exit__(self, *_exc) -> None:
        return None


_NOOP = _Noop()


class _ActiveSpan:
    """Per-call object; populated by ``span()`` and pushes durations on exit."""

    __slots__ = ('_stage', '_t0')

    def __init__(self, stage: str) -> None:
        self._stage = stage
        self._t0 = 0.0

    def __enter__(self) -> '_ActiveSpan':
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        dt_ms = (time.perf_counter() - self._t0) * 1000.0
        _record(self._stage, dt_ms)


# Per-process state. ``_state`` is None until ``configure()`` is called;
# until then ``span()`` still records into a buffer keyed by stage so we
# don't lose pre-configure events (rare — only at startup), but they're
# only flushed after configure(). When disabled, _state stays None and
# _record is never invoked.
_state: Optional[dict] = None


def configure(role: str, id: int) -> None:  # noqa: A002 — match spec API
    """One-time per-process init. Idempotent — repeat calls overwrite role/id
    only when not yet configured (silent no-op otherwise to avoid stale
    handle leaks under double-init)."""
    if not _ENABLED:
        return
    global _state
    if _state is not None:
        # Already configured. Treat as no-op so a paradigm that calls
        # configure twice (e.g. tests reusing a process) doesn't double-
        # open handles.
        return
    log_dir = Path(os.getenv('PERF_TRACE_DIR', 'artifacts/_perf_logs'))
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f'{role}_{id}.jsonl'
    # Append mode so multiple runs into the same dir accumulate (analyze
    # script can split by run via timestamps if needed). Line-buffered so
    # crashes preserve partial data.
    fh = open(path, 'a', buffering=1, encoding='utf-8')
    _state = {
        'role': role,
        'id': id,
        'path': path,
        'fh': fh,
        'buckets': {},  # stage → list[ms]
        'n_events': 0,
        'last_flush_ts': time.perf_counter(),
    }


def span(stage: str):
    """Context manager that times the block as ``stage``.

    Hot path when disabled: single global load + identity return of the
    pre-allocated _NOOP. No string formatting, no dict access.
    """
    if not _ENABLED:
        return _NOOP
    return _ActiveSpan(stage)


def value(stage: str, v: float) -> None:
    """Record a non-duration numeric value under ``stage`` (e.g. batch size).

    Stored in the same per-stage bucket as durations; the JSON output
    naming says ``mean_ms`` / ``p95_ms`` regardless — the analyzer
    distinguishes by stage name convention (``*.size`` vs ``*.ms`` /
    plain). Caller must pick a stage name that signals units."""
    if not _ENABLED:
        return
    _record(stage, float(v))


def _record(stage: str, v: float) -> None:
    if _state is None:
        return
    bucket = _state['buckets'].get(stage)
    if bucket is None:
        bucket = []
        _state['buckets'][stage] = bucket
    bucket.append(v)
    _state['n_events'] += 1
    if _state['n_events'] >= _FLUSH_WINDOW:
        _flush()
        return
    # Wall-time fallback so a slow stage with few events still flushes.
    if time.perf_counter() - _state['last_flush_ts'] >= _FLUSH_INTERVAL_S:
        _flush()


def _percentile(sorted_vals: list, p: float) -> float:
    """p in [0, 100]. Linear interp between ranks; matches numpy default."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _flush() -> None:
    if _state is None or not _state['buckets']:
        if _state is not None:
            _state['last_flush_ts'] = time.perf_counter()
        return
    stages_out = {}
    window_n = 0
    for stage, vals in _state['buckets'].items():
        if not vals:
            continue
        s = sorted(vals)
        n = len(s)
        window_n += n
        stages_out[stage] = {
            'n': n,
            'sum_ms': round(sum(s), 4),
            'mean_ms': round(sum(s) / n, 4),
            'p50_ms': round(_percentile(s, 50.0), 4),
            'p95_ms': round(_percentile(s, 95.0), 4),
            'max_ms': round(s[-1], 4),
        }
    row = {
        'ts_unix': round(time.time(), 3),
        'role': _state['role'],
        'id': _state['id'],
        'window_n': window_n,
        'stages': stages_out,
    }
    try:
        _state['fh'].write(json.dumps(row) + '\n')
    except Exception:  # pragma: no cover — fh closed during shutdown race
        pass
    # Reset buckets (reuse dict instance to avoid realloc churn).
    for vals in _state['buckets'].values():
        vals.clear()
    _state['n_events'] = 0
    _state['last_flush_ts'] = time.perf_counter()


def close() -> None:
    """Flush + close. Safe to call when disabled or already closed."""
    if not _ENABLED or _state is None:
        return
    _flush()
    try:
        _state['fh'].close()
    except Exception:  # pragma: no cover
        pass
    # Don't None out _state — calling configure again would silently
    # double-open. Setting fh to a closed handle is enough; subsequent
    # _record calls just no-op the write attempt. (close should be final.)
    _state['fh'] = None


def is_enabled() -> bool:
    """Test-only helper."""
    return _ENABLED
