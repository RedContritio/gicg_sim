"""Tests for training.core.perf.trace — zero-overhead-off + flush + format。

Post 2026-05-23 cfg-driven 改造:模块不再 import-time-gate on env var,
``_ENABLED`` 由 :func:`trace.enable_explicit` / :func:`trace.enable_from_cfg`
mutate。 fixture 直接 set + tear-down 复位,无 ``importlib.reload`` 必要。
"""

from __future__ import annotations

import json
import time

import pytest

import training.core.perf.trace as _trace_mod


@pytest.fixture
def perf_on(tmp_path):
    """Enable trace with small flush window + per-test tmp log dir。 tear-down
    复位 disabled + 关已开的 handle,unrelated 测试看到原 no-op behavior。"""
    _trace_mod.enable_explicit(flush_window=5, flush_interval_s=1.0, log_dir=str(tmp_path))
    yield _trace_mod, tmp_path
    # 显式 close 兜 fixture 期间未调 close 的测试,避免 handle 泄漏。
    try:
        _trace_mod.close()
    except Exception:
        pass
    # 复位 module state -> disabled,后续测试看 _NOOP hot path。
    _trace_mod._ENABLED = False
    _trace_mod._state = None
    _trace_mod._FLUSH_WINDOW = 200
    _trace_mod._FLUSH_INTERVAL_S = 1.0
    _trace_mod._LOG_DIR = 'artifacts/_perf_logs'


def test_span_is_noop_when_disabled():
    """Default (无 enable_explicit 调) → span() 返 shared _NOOP 单例。"""
    assert _trace_mod._ENABLED is False
    cm1 = _trace_mod.span('a')
    cm2 = _trace_mod.span('b')
    assert cm1 is _trace_mod._NOOP
    assert cm2 is _trace_mod._NOOP
    # configure/close 在 disabled 下是 no-op + 不创 log dir。
    _trace_mod.configure(role='actor', id=0)
    _trace_mod.close()


def test_span_records_when_enabled(perf_on):
    trace, tmp_path = perf_on
    trace.configure(role='test', id=7)
    for _ in range(12):
        with trace.span('stage_a'):
            time.sleep(0.001)
    trace.close()
    log = tmp_path / 'test_7.jsonl'
    assert log.exists()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    # 12 events / flush_n=5 → ≥ 2 full flushes + final flush on close
    assert len(rows) >= 2
    total_n = sum(row['stages'].get('stage_a', {}).get('n', 0) for row in rows)
    assert total_n == 12
    for row in rows:
        assert row['role'] == 'test'
        assert row['id'] == 7
        st = row['stages']['stage_a']
        for k in ('n', 'sum_ms', 'mean_ms', 'p50_ms', 'p95_ms', 'max_ms'):
            assert k in st


def test_value_records_under_stage(perf_on):
    trace, tmp_path = perf_on
    trace.configure(role='r', id=0)
    for v in (1.0, 2.0, 3.0, 4.0, 5.0):
        trace.value('batch.size', v)
    trace.close()
    log = tmp_path / 'r_0.jsonl'
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    seen = sum(row['stages'].get('batch.size', {}).get('n', 0) for row in rows)
    assert seen == 5
    # mean = (1+2+3+4+5)/5 = 3
    means = [row['stages']['batch.size']['mean_ms'] for row in rows if 'batch.size' in row['stages']]
    # First flush at N=5 → mean 3.0, then close flush has nothing
    assert any(abs(m - 3.0) < 0.001 for m in means)


def test_configure_idempotent(perf_on):
    """Double-configure must not double-open handles."""
    trace, _ = perf_on
    trace.configure(role='r', id=0)
    fh1 = trace._state['fh']
    trace.configure(role='r', id=0)
    fh2 = trace._state['fh']
    assert fh1 is fh2
    trace.close()


def test_nested_spans_record_both(perf_on):
    trace, tmp_path = perf_on
    trace.configure(role='r', id=0)
    for _ in range(5):
        with trace.span('outer'):
            with trace.span('inner'):
                time.sleep(0.0005)
    trace.close()
    log = tmp_path / 'r_0.jsonl'
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    outer_n = sum(row['stages'].get('outer', {}).get('n', 0) for row in rows)
    inner_n = sum(row['stages'].get('inner', {}).get('n', 0) for row in rows)
    assert outer_n == 5
    assert inner_n == 5


def test_percentile_helper_edge_cases():
    p = _trace_mod._percentile
    assert p([], 50) == 0.0
    assert p([1.0], 95) == 1.0
    # known: [1,2,3,4,5] p50 = 3
    assert abs(p([1.0, 2.0, 3.0, 4.0, 5.0], 50.0) - 3.0) < 1e-9
    # p95 of [1..100] = 95.05 (linear interp k=94.05)
    arr = sorted(float(i) for i in range(1, 101))
    assert abs(p(arr, 95.0) - 95.05) < 0.01


def test_enable_from_cfg_reads_debug_section():
    """cfg.debug.perf_trace=True + 配套字段 → _ENABLED + 参数 reflect cfg。"""
    from training.core.config.base import DebugCfg

    class _Cfg:
        debug = DebugCfg(perf_trace=True, perf_trace_flush_n=42, perf_trace_flush_s=0.5)

    _trace_mod.enable_from_cfg(_Cfg())
    try:
        assert _trace_mod._ENABLED is True
        assert _trace_mod._FLUSH_WINDOW == 42
        assert abs(_trace_mod._FLUSH_INTERVAL_S - 0.5) < 1e-9
    finally:
        _trace_mod._ENABLED = False
        _trace_mod._FLUSH_WINDOW = 200
        _trace_mod._FLUSH_INTERVAL_S = 1.0


def test_enable_from_cfg_disabled_no_op():
    """cfg.debug.perf_trace=False (default) → _ENABLED 保持 False。"""
    from training.core.config.base import DebugCfg

    class _Cfg:
        debug = DebugCfg()  # all False

    _trace_mod._ENABLED = False
    _trace_mod.enable_from_cfg(_Cfg())
    assert _trace_mod._ENABLED is False


def test_enable_from_cfg_missing_debug_no_op():
    """cfg 无 debug attr (老对象 / mock) → no-op,不 raise。"""

    class _Cfg:
        pass

    _trace_mod._ENABLED = False
    _trace_mod.enable_from_cfg(_Cfg())
    assert _trace_mod._ENABLED is False
