"""Tests for training.core.perf.trace — zero-overhead-off + flush + format.

The module is import-time-gated on ``PERF_TRACE`` env var, so we cannot
test on/off in the same process. We rely on ``importlib.reload`` with a
monkeypatched env to flip ``_ENABLED`` mid-test, and on subprocess for
the multi-process role test.
"""

from __future__ import annotations

import importlib
import json
import time

import pytest

import training.core.perf.trace as _trace_mod


@pytest.fixture
def perf_on(monkeypatch, tmp_path):
    """Reload trace module with PERF_TRACE=1 + a clean log dir.

    The fixture sets a small flush window so we don't have to fake 200
    events per test. Restores the module to its original gating after
    the test so subsequent tests (and trace imports elsewhere) see the
    original env behavior."""
    monkeypatch.setenv('PERF_TRACE', '1')
    monkeypatch.setenv('PERF_TRACE_DIR', str(tmp_path))
    monkeypatch.setenv('PERF_TRACE_FLUSH_N', '5')
    importlib.reload(_trace_mod)
    yield _trace_mod, tmp_path
    # Reset module state back to disabled so unrelated tests see no-op
    monkeypatch.delenv('PERF_TRACE', raising=False)
    importlib.reload(_trace_mod)


def test_span_is_noop_when_disabled():
    """PERF_TRACE unset → span() returns the shared _NOOP singleton."""
    # Use module as-imported (gating evaluated at import; tests run
    # without PERF_TRACE set in the test env).
    assert _trace_mod._ENABLED is False
    cm1 = _trace_mod.span('a')
    cm2 = _trace_mod.span('b')
    assert cm1 is _trace_mod._NOOP
    assert cm2 is _trace_mod._NOOP
    # configure/close are no-ops; calling them must not raise + not
    # create any file (no log dir).
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
    trace, tmp_path = perf_on
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
