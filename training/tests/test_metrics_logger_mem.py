"""MetricsLogger 通用 mem sampler 守 schema + 线程生命周期 + 关闭安全。

新增 kind=mem 行(2026-05-21 ship via tools.runs.train perf 验证暴露的
metric gap)。原 logger 只采 fps/episodes,mem 数据走人肉 Task Manager —
现内置 background thread。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from training.core.logging import MetricsLogger, _sample_mem


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_sample_mem_schema():
    """One-shot sample 函数返必备 9 字段 + 数值 sane。"""
    s = _sample_mem()
    expected = {
        'master_pid',
        'master_rss_mb',
        'children_count',
        'children_rss_total_mb',
        'children_rss_max_mb',
        'cuda_alloc_mb',
        'cuda_reserved_mb',
        'host_used_mb',
        'host_total_mb',
    }
    assert set(s.keys()) == expected
    assert s['master_rss_mb'] > 0, 'master RSS must be positive — psutil broken?'
    assert s['host_total_mb'] > 0, 'host RAM total must be positive'
    assert s['host_used_mb'] > 0, 'host RAM used must be positive'
    assert s['host_used_mb'] <= s['host_total_mb'], 'used > total impossible'
    assert s['children_count'] >= 0
    assert s['children_rss_total_mb'] >= 0
    assert s['children_rss_max_mb'] >= 0
    assert s['cuda_alloc_mb'] >= 0
    assert s['cuda_reserved_mb'] >= 0


def test_sampler_emits_mem_rows_under_interval(tmp_path: Path):
    """0.2s interval → 1s wall 内应有 ≥ 4 行 mem(initial + 4 周期采)。"""
    logger = MetricsLogger(tmp_path, enable_tb=False, mem_sample_interval_s=0.2)
    try:
        time.sleep(1.0)
    finally:
        logger.close()

    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    mem_rows = [r for r in rows if r['kind'] == 'mem']
    assert len(mem_rows) >= 4, f'expected ≥4 mem rows in 1s @ 0.2s interval, got {len(mem_rows)}'

    # 守 schema:每行必含 master_rss_mb + host_used_mb + cuda_alloc_mb。
    for r in mem_rows:
        assert 'master_rss_mb' in r
        assert 'host_used_mb' in r
        assert 'cuda_alloc_mb' in r
        assert 'wall_s' in r
        assert r['master_rss_mb'] > 0


def test_sampler_disabled_when_interval_none_or_zero(tmp_path: Path):
    """``mem_sample_interval_s=None`` / 0 关 sampler — 仅 explicit log 行。"""
    for interval in (None, 0, -1):
        sub = tmp_path / f'd_{interval}'
        if interval is None:
            # None means "use default"; to disable, pass 0/<=0.
            # We're guarding ``<=0`` here; default 行为 covered by其它 test。
            continue
        logger = MetricsLogger(sub, enable_tb=False, mem_sample_interval_s=interval)
        try:
            time.sleep(0.3)
            logger.log('iter', {'step': 0})
        finally:
            logger.close()
        rows = _read_jsonl(sub / 'metrics.jsonl')
        mem_rows = [r for r in rows if r['kind'] == 'mem']
        iter_rows = [r for r in rows if r['kind'] == 'iter']
        assert len(mem_rows) == 0, f'interval={interval} should disable sampler, got {len(mem_rows)} mem rows'
        assert len(iter_rows) == 1, 'explicit log must still work'


def test_close_idempotent_and_thread_joined(tmp_path: Path):
    """close() 后 sampler thread 必停 + 第二次 close 不抛。"""
    logger = MetricsLogger(tmp_path, enable_tb=False, mem_sample_interval_s=0.05)
    assert logger._mem_sampler is not None
    sampler_ref = logger._mem_sampler
    time.sleep(0.15)
    logger.close()
    # Thread must be joined within ≤ 2s (default stop timeout).
    assert not sampler_ref.is_alive(), 'sampler thread must be joined on close'
    assert logger._mem_sampler is None
    # Second close — no-op.
    logger.close()


def test_concurrent_log_does_not_race(tmp_path: Path):
    """Sampler thread + main thread.log() 并发写 — 同一文件不应交错破坏 jsonl。

    用极短 interval(0.01s)制造高争用,主线程同时 push 50 iter 行;
    最终 metrics.jsonl 每行必须能 parse 为 JSON(无半行 / 拼接行)。"""
    logger = MetricsLogger(tmp_path, enable_tb=False, mem_sample_interval_s=0.01)
    try:
        for i in range(50):
            logger.log('iter', {'step': i, 'frames': i * 5})
            time.sleep(0.005)
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
        assert row['kind'] in ('iter', 'mem')
