"""MetricsLogger.attach_callable_sampler — 单测 callable sampler 公共 API。

验证:
1. callable sampler 注册后写入 metrics.jsonl(至少 1 行)
2. payload 字段原样落盘
3. 无 artifacts_dir 时 no-op(不起线程)
4. close() 后 sampler thread join(不 alive)
5. 多 callable sampler 并发写不 race
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from training.core.logging import MetricsLogger


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _all_samplers_off() -> dict:
    """Disable all built-in samplers — only test the callable sampler under test."""
    return {
        'mem_sample_interval_s': 0,
        'cpu_sample_interval_s': 0,
        'gpu_sample_interval_s': 0,
        'disk_sample_interval_s': 0,
        'net_sample_interval_s': 0,
        'load_sample_interval_s': 0,
    }


# ---------------------------------------------------------------------------
# Core emission test
# ---------------------------------------------------------------------------


def test_callable_sampler_emits_rows_to_metrics_jsonl(tmp_path: Path):
    """attach_callable_sampler 注册 + sleep 后 close — metrics.jsonl 有 ≥ 1 行
    kind='fake_sampler',payload 含 {'value': 42}。"""
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_samplers_off())
    logger.attach_callable_sampler('fake_sampler', 0.1, lambda: {'value': 42})
    try:
        time.sleep(0.4)
    finally:
        logger.close()

    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    sampler_rows = [r for r in rows if r['kind'] == 'fake_sampler']
    assert len(sampler_rows) >= 1, f'expected ≥1 fake_sampler rows, got {len(sampler_rows)}'
    for r in sampler_rows:
        assert r['value'] == 42
        assert 'wall_s' in r


def test_callable_sampler_noop_without_artifacts_dir():
    """no artifacts_dir → attach_callable_sampler は no-op,不起线程,不抛。"""
    logger = MetricsLogger(None, enable_tb=False)
    n_before = len(logger._samplers)
    logger.attach_callable_sampler('fake_sampler', 0.1, lambda: {'v': 1})
    assert len(logger._samplers) == n_before, 'sampler thread must not be created without artifacts_dir'
    logger.close()


def test_callable_sampler_thread_joined_on_close(tmp_path: Path):
    """close() 后 callable sampler thread 不再 alive。"""
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_samplers_off())
    logger.attach_callable_sampler('fake_sampler', 0.05, lambda: {'v': 1})
    sampler_refs = list(logger._samplers)
    time.sleep(0.15)
    logger.close()
    for s in sampler_refs:
        assert not s.is_alive(), f'sampler {s.name} must be joined on close()'
    assert logger._samplers == []


def test_callable_sampler_multiple_kinds_no_race(tmp_path: Path):
    """多个 callable sampler 并发写 — 每行 valid JSON,kind 正确。"""
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_samplers_off())
    logger.attach_callable_sampler('kind_a', 0.02, lambda: {'x': 1})
    logger.attach_callable_sampler('kind_b', 0.03, lambda: {'y': 2})
    try:
        time.sleep(0.3)
    finally:
        logger.close()

    raw = (tmp_path / 'metrics.jsonl').read_text(encoding='utf-8')
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            pytest.fail(f'line {line_no} not valid JSON (race?): {line!r} — {e}')
        assert row['kind'] in ('kind_a', 'kind_b'), f'unexpected kind: {row["kind"]}'

    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    assert len([r for r in rows if r['kind'] == 'kind_a']) >= 1
    assert len([r for r in rows if r['kind'] == 'kind_b']) >= 1


def test_callable_sampler_exception_in_fn_does_not_kill_sampler(tmp_path: Path):
    """sample_fn 抛异常时 sampler thread 继续运行(swallow pattern)— 后续 call 仍写行。"""
    call_count = [0]

    def flaky_fn() -> dict:
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError('boom')
        return {'call': call_count[0]}

    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_samplers_off())
    logger.attach_callable_sampler('flaky', 0.05, flaky_fn)
    try:
        time.sleep(0.4)
    finally:
        logger.close()

    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    flaky_rows = [r for r in rows if r['kind'] == 'flaky']
    # 第 1 次调用抛异常(swallowed),第 2+ 次正常 — 应有 ≥ 1 成功行。
    assert len(flaky_rows) >= 1, 'sampler must survive exception + continue emitting'
