"""MetricsLogger 通用 sampler 守 schema + 线程生命周期 + 并发安全。

Sampler kinds:mem / cpu / gpu(nvidia-smi 可用时)/ disk / net / load(Unix
only)。每个 kind 走同一 ``_ResourceSamplerThread`` 抽象,本测试守:
- 每个 sample_fn 单独 schema(_sample_*)
- 各 sampler 启停 + interval 行为
- 多 sampler 并发写不 race
- close() 幂等 + thread join

注:os-specific samplers(gpu / load)在不支持平台不起,测试需 conditionally skip。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from training.core.logging import MetricsLogger
from training.core.logging_samplers import (
    _nvidia_smi_available,
    _sample_cpu,
    _sample_disk,
    _sample_gpu,
    _sample_load,
    _sample_mem,
    _sample_net,
)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Per-sampler one-shot schema tests
# ---------------------------------------------------------------------------


def test_sample_cpu_schema():
    import psutil

    psutil.cpu_percent(interval=None, percpu=True)  # prime
    s = _sample_cpu()
    assert set(s.keys()) == {'per_core_pct', 'avg_pct', 'max_pct', 'n_cores'}
    assert s['n_cores'] > 0
    assert len(s['per_core_pct']) == s['n_cores']
    assert all(0 <= p <= 100 for p in s['per_core_pct'])
    assert 0 <= s['avg_pct'] <= 100
    assert 0 <= s['max_pct'] <= 100


def test_sample_mem_schema():
    """One-shot mem snapshot — full 22-field set(master + children agg + cuda +
    host + tracemalloc opt)。"""
    s = _sample_mem()
    expected = {
        'master_pid',
        'master_rss_mb',
        'master_num_threads',
        'master_num_fds',
        'master_ctx_vol',
        'master_ctx_invol',
        'master_io_read_mb',
        'master_io_write_mb',
        'children_count',
        'children_rss_total_mb',
        'children_rss_max_mb',
        'children_num_threads_total',
        'children_num_fds_total',
        'children_ctx_vol_total',
        'children_ctx_invol_total',
        'children_io_read_mb',
        'children_io_write_mb',
        'cuda_alloc_mb',
        'cuda_reserved_mb',
        'host_used_mb',
        'host_total_mb',
        'tracemalloc_total_mb',
    }
    assert set(s.keys()) == expected
    assert s['master_rss_mb'] > 0
    assert s['host_total_mb'] > 0
    assert s['host_used_mb'] > 0
    assert s['host_used_mb'] <= s['host_total_mb']
    assert s['children_count'] >= 0
    # 各 None / 数值都允许 — 仅守某些 OS 上 io_counters 不可读 时 graceful。
    # master_num_threads 在所有 OS 都该 ≥ 1。
    assert s['master_num_threads'] is None or s['master_num_threads'] >= 1
    # tracemalloc 默认未 start → None;若 test 进程 之前 start 过(其他 test
    # 触发)则 数值 ≥ 0。 不强 require 任一情况,只 schema 校。
    assert s['tracemalloc_total_mb'] is None or s['tracemalloc_total_mb'] >= 0


def test_sample_mem_with_tracemalloc_active():
    """tracemalloc.is_tracing() True 时 _sample_mem 返 数值 而非 None。"""
    import tracemalloc

    already_tracing = tracemalloc.is_tracing()
    if not already_tracing:
        tracemalloc.start()
    try:
        s = _sample_mem()
        assert s['tracemalloc_total_mb'] is not None
        assert s['tracemalloc_total_mb'] >= 0
    finally:
        if not already_tracing:
            tracemalloc.stop()


def test_sample_disk_schema():
    s = _sample_disk()
    assert set(s.keys()) == {'read_mb', 'write_mb', 'read_count', 'write_count'}
    # psutil.disk_io_counters() 在某些 sandbox 容器返 None — graceful。
    if s['read_mb'] is not None:
        assert s['read_mb'] >= 0
        assert s['write_mb'] >= 0
        assert s['read_count'] >= 0
        assert s['write_count'] >= 0


def test_sample_net_schema():
    s = _sample_net()
    assert set(s.keys()) == {'bytes_sent_mb', 'bytes_recv_mb', 'packets_sent', 'packets_recv'}
    if s['bytes_sent_mb'] is not None:
        assert s['bytes_sent_mb'] >= 0
        assert s['bytes_recv_mb'] >= 0


@pytest.mark.skipif(not hasattr(os, 'getloadavg'), reason='load avg Unix-only (Win has no equivalent)')
def test_sample_load_schema():
    s = _sample_load()
    assert set(s.keys()) == {'load_1m', 'load_5m', 'load_15m'}
    assert s['load_1m'] >= 0
    assert s['load_5m'] >= 0
    assert s['load_15m'] >= 0


@pytest.mark.skipif(not _nvidia_smi_available(), reason='nvidia-smi not installed (no GPU box)')
def test_sample_gpu_schema():
    s = _sample_gpu()
    assert 'devices' in s
    assert 'n_devices' in s
    assert s['n_devices'] >= 0
    for dev in s['devices']:
        expected = {
            'gpu_util_pct',
            'mem_util_pct',
            'mem_used_mb',
            'mem_total_mb',
            'temperature_c',
            'power_w',
            'fan_pct',
            'clock_gr_mhz',
            'clock_mem_mhz',
        }
        assert set(dev.keys()) == expected


# ---------------------------------------------------------------------------
# Sampler thread lifecycle + interval behavior
# ---------------------------------------------------------------------------


def _all_off_except(**kw) -> dict:
    """Helper:返 MetricsLogger ctor kwargs disable 所有 sampler 后只开 kw 指定的。"""
    base = {
        'mem_sample_interval_s': 0,
        'cpu_sample_interval_s': 0,
        'gpu_sample_interval_s': 0,
        'disk_sample_interval_s': 0,
        'net_sample_interval_s': 0,
        'load_sample_interval_s': 0,
    }
    base.update(kw)
    return base


def test_sampler_emits_mem_rows_under_interval(tmp_path: Path):
    """0.2s interval → 1s wall 内应有 ≥ 4 行 mem。"""
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_off_except(mem_sample_interval_s=0.2))
    try:
        time.sleep(1.0)
    finally:
        logger.close()
    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    mem_rows = [r for r in rows if r['kind'] == 'mem']
    assert len(mem_rows) >= 4
    for r in mem_rows:
        assert 'master_rss_mb' in r
        assert 'host_used_mb' in r
        assert 'master_num_threads' in r
        assert r['master_rss_mb'] > 0


def test_sampler_emits_cpu_rows_under_interval(tmp_path: Path):
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_off_except(cpu_sample_interval_s=0.2))
    try:
        time.sleep(1.0)
    finally:
        logger.close()
    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    cpu_rows = [r for r in rows if r['kind'] == 'cpu']
    assert len(cpu_rows) >= 4
    for r in cpu_rows:
        assert 'per_core_pct' in r
        assert len(r['per_core_pct']) == r['n_cores']


def test_sampler_emits_disk_net_rows_under_interval(tmp_path: Path):
    """disk + net sampler 同时启短间隔。"""
    logger = MetricsLogger(
        tmp_path,
        enable_tb=False,
        **_all_off_except(disk_sample_interval_s=0.2, net_sample_interval_s=0.2),
    )
    try:
        time.sleep(1.0)
    finally:
        logger.close()
    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    disk_rows = [r for r in rows if r['kind'] == 'disk']
    net_rows = [r for r in rows if r['kind'] == 'net']
    assert len(disk_rows) >= 4
    assert len(net_rows) >= 4


@pytest.mark.skipif(not hasattr(os, 'getloadavg'), reason='load avg Unix-only')
def test_sampler_emits_load_rows_under_interval(tmp_path: Path):
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_off_except(load_sample_interval_s=0.2))
    try:
        time.sleep(1.0)
    finally:
        logger.close()
    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    load_rows = [r for r in rows if r['kind'] == 'load']
    assert len(load_rows) >= 4


def test_sampler_disabled_when_interval_zero_or_negative(tmp_path: Path):
    """所有 sampler interval = 0 → 只 explicit log 行,无任何采样行。"""
    for interval in (0, -1):
        sub = tmp_path / f'd_{interval}'
        logger = MetricsLogger(
            sub,
            enable_tb=False,
            mem_sample_interval_s=interval,
            cpu_sample_interval_s=interval,
            gpu_sample_interval_s=interval,
            disk_sample_interval_s=interval,
            net_sample_interval_s=interval,
            load_sample_interval_s=interval,
        )
        try:
            time.sleep(0.3)
            logger.log('iter', {'step': 0})
        finally:
            logger.close()
        rows = _read_jsonl(sub / 'metrics.jsonl')
        sampler_rows = [r for r in rows if r['kind'] in ('mem', 'cpu', 'gpu', 'disk', 'net', 'load')]
        iter_rows = [r for r in rows if r['kind'] == 'iter']
        assert sampler_rows == []
        assert len(iter_rows) == 1


def test_gpu_sampler_skipped_when_nvidia_smi_absent(tmp_path: Path):
    """无 nvidia-smi 时 gpu sampler 不启(即使 user 显式传 interval)。"""
    if _nvidia_smi_available():
        pytest.skip('nvidia-smi present — cannot test absent-skip path')
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_off_except(gpu_sample_interval_s=0.05))
    try:
        time.sleep(0.2)
    finally:
        logger.close()
    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    assert [r for r in rows if r['kind'] == 'gpu'] == [], 'gpu sampler should not start without nvidia-smi'


def test_load_sampler_skipped_on_windows(tmp_path: Path):
    """Win 无 getloadavg → load sampler 不启。"""
    if hasattr(os, 'getloadavg'):
        pytest.skip('Unix platform — load avg supported')
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_off_except(load_sample_interval_s=0.05))
    try:
        time.sleep(0.2)
    finally:
        logger.close()
    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    assert [r for r in rows if r['kind'] == 'load'] == []


def test_close_idempotent_and_threads_joined(tmp_path: Path):
    """close() 后所有 sampler thread 必停 + 第二次 close 不抛。"""
    logger = MetricsLogger(
        tmp_path,
        enable_tb=False,
        mem_sample_interval_s=0.05,
        cpu_sample_interval_s=0.05,
        disk_sample_interval_s=0.05,
        net_sample_interval_s=0.05,
        gpu_sample_interval_s=0.05,  # gpu skip if no nvidia-smi
        load_sample_interval_s=0.05,  # load skip if Win
    )
    # 至少 mem + cpu + disk + net 4 个肯定起;gpu / load 视平台而定。
    assert len(logger._samplers) >= 4
    sampler_refs = list(logger._samplers)
    time.sleep(0.15)
    logger.close()
    for s in sampler_refs:
        assert not s.is_alive(), f'sampler {s.name} must be joined on close'
    assert logger._samplers == []
    logger.close()  # second close — no-op


def test_attach_external_queue_drains_to_metrics_jsonl(tmp_path: Path):
    """attach_external_queue + push tuple → drainer thread 写入 metrics.jsonl。

    用标准库 ``queue.Queue`` 替代 mp.Queue(线程版,接口兼容,测试不用 spawn
    subprocess)。守 (kind, payload) 格式行抵达 + 错误 item 被 silently dropped。"""
    import queue as q_mod

    q = q_mod.Queue()
    logger = MetricsLogger(tmp_path, enable_tb=False, **_all_off_except())
    logger.attach_external_queue(q, name='unit_test')
    try:
        q.put(('inf_server', {'queue_depth_avg': 3.5, 'batch_size_avg': 8.0}))
        q.put(('inf_server', {'queue_depth_avg': 4.0, 'batch_size_avg': 9.0}))
        # Garbage shapes — should be silently dropped:
        q.put('not_a_tuple')
        q.put(('bad', 'payload_not_dict'))
        q.put(('only_one_field',))
        time.sleep(0.3)  # drainer poll = 0.1s
    finally:
        logger.close()

    rows = _read_jsonl(tmp_path / 'metrics.jsonl')
    inf_rows = [r for r in rows if r['kind'] == 'inf_server']
    assert len(inf_rows) == 2
    assert inf_rows[0]['queue_depth_avg'] == 3.5
    assert inf_rows[1]['batch_size_avg'] == 9.0
    # 不该有 garbage 行。
    assert all(r['kind'] in ('inf_server',) for r in rows)


def test_concurrent_log_does_not_race(tmp_path: Path):
    """所有 sampler + main thread.log() 并发写 — 每行 valid JSON。"""
    logger = MetricsLogger(
        tmp_path,
        enable_tb=False,
        mem_sample_interval_s=0.01,
        cpu_sample_interval_s=0.01,
        disk_sample_interval_s=0.01,
        net_sample_interval_s=0.01,
        gpu_sample_interval_s=0.01,
        load_sample_interval_s=0.01,
    )
    try:
        for i in range(50):
            logger.log('iter', {'step': i, 'frames': i * 5})
            time.sleep(0.005)
    finally:
        logger.close()

    raw = (tmp_path / 'metrics.jsonl').read_text(encoding='utf-8')
    valid_kinds = {'iter', 'mem', 'cpu', 'gpu', 'disk', 'net', 'load', 'go_perf'}
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            pytest.fail(f'line {line_no} not valid JSON (race?): {line!r} — {e}')
        assert row['kind'] in valid_kinds
