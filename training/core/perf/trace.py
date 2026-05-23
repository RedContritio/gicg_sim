"""Paradigm-agnostic perf trace — zero overhead when disabled.

Activation (cfg-driven,post 2026-05-23):cfg ``[debug] perf_trace = true``
+ optional ``perf_trace_flush_n / _flush_s / _dir`` overrides。 每 process
(pipeline / actor / inference server) 在 spawn target 起步时调一次
:func:`enable_from_cfg` (或 :func:`enable_explicit` for tests / non-cfg
contexts) → 设 module-level ``_ENABLED``,后续 :func:`configure` 才真分配
handle。 Hot path 当 disabled 仍是 single attribute load + branch (返
shared ``_NOOP`` 单例,无 alloc / 无 perf_counter)。

API:

    from training.core.perf import trace
    trace.enable_from_cfg(cfg)                 # spawn target 入口一次
    trace.configure(role='actor', id=0)        # idempotent per process
    with trace.span('env.step'):
        env.step(action)
    trace.close()                              # flush + close handle

Output: ``<log_dir>/<role>_<id>.jsonl`` (default
``artifacts/_perf_logs``,可由 cfg ``debug.perf_trace_dir`` 覆盖,主供测试
隔离用)。 每行 aggregate ``_FLUSH_WINDOW`` events 为单 JSON row,含
mean/p50/p95/max/sum/n per stage。 低速 stage 由 ``_FLUSH_INTERVAL_S``
wall timer 兜底 flush。
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Optional

_ENABLED = False
_FLUSH_WINDOW = 200
_FLUSH_INTERVAL_S = 1.0
_LOG_DIR = 'artifacts/_perf_logs'


def enable_explicit(
    *,
    flush_window: int = 200,
    flush_interval_s: float = 1.0,
    log_dir: Optional[str] = None,
) -> None:
    """Programmatic enable (tests / subprocess args / non-cfg paths)。

    Must be called *before* :func:`configure`。 Subsequent calls reset
    parameters but only the first :func:`configure` opens the handle。"""
    global _ENABLED, _FLUSH_WINDOW, _FLUSH_INTERVAL_S, _LOG_DIR
    _ENABLED = True
    _FLUSH_WINDOW = int(flush_window)
    _FLUSH_INTERVAL_S = float(flush_interval_s)
    if log_dir is not None:
        _LOG_DIR = str(log_dir)


def enable_from_cfg(cfg: Any) -> None:
    """cfg-driven enable — read ``cfg.debug.perf_trace`` + 配套字段。 cfg.debug
    缺失或 perf_trace=False 时 no-op (留 disabled state)。 spawn target 入口
    标准调用点(``run_paradigm_train`` / ``actor_main`` / ``_server_loop``)。"""
    dbg = getattr(cfg, 'debug', None)
    if dbg is None or not getattr(dbg, 'perf_trace', False):
        return
    enable_explicit(
        flush_window=getattr(dbg, 'perf_trace_flush_n', 200),
        flush_interval_s=getattr(dbg, 'perf_trace_flush_s', 1.0),
        log_dir=getattr(dbg, 'perf_trace_dir', None),
    )


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
    log_dir = Path(_LOG_DIR)
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
