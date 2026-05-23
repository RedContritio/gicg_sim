"""Go-side perf trace ctypes bridge — flush + decode + enable/disable 路径。

Post 2026-05-23 cfg-driven 改造:启用走 capi gicg_actor_set_perf_trace_enabled
(由 :func:`set_go_perf_trace_enabled` 暴露给 Python),旧 env var
GICG_GO_PERF_TRACE 已废。 lib load 后 set 即可生效 — 无 init-time gate,
主测试进程 + subprocess 都能 enable / disable 切换。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _lib_built() -> bool:
    name = {'darwin': 'libgicg_actor.dylib', 'win32': 'libgicg_actor.dll'}.get(sys.platform, 'libgicg_actor.so')
    return (Path(__file__).resolve().parents[4] / 'gicg_env' / name).exists()


@pytest.mark.skipif(not _lib_built(), reason='libgicg_actor not built')
def test_flush_returns_empty_when_disabled():
    """disabled (default 起,未调 set_go_perf_trace_enabled(True)) 时 flush 返 []。"""
    from training.core.actor.go_perf_trace import (
        flush_go_perf_spans,
        go_perf_trace_enabled,
        set_go_perf_trace_enabled,
    )

    # 显式 set False —— 防本 test 与下方 enable test 顺序耦合(本进程 lib 仅 load 一次)。
    set_go_perf_trace_enabled(False)
    assert not go_perf_trace_enabled()
    assert flush_go_perf_spans() == []


@pytest.mark.skipif(not _lib_built(), reason='libgicg_actor not built')
def test_set_enabled_toggles_state():
    """set_go_perf_trace_enabled(True/False) 实时反映到 go_perf_trace_enabled() —
    cfg-driven 启用路径取代旧 init-time env var sample。"""
    from training.core.actor.go_perf_trace import (
        flush_go_perf_spans,
        go_perf_trace_enabled,
        set_go_perf_trace_enabled,
    )

    try:
        set_go_perf_trace_enabled(True)
        assert go_perf_trace_enabled() is True
        # 无 span 触发 → ring 空。 真聚合 verify 走 Go side TestPerfTraceEnabledAggregation。
        assert flush_go_perf_spans() == []
    finally:
        # 复位 —— 同 process 中后续 test (sampler / 其他 module) 不应看到残留 enable。
        set_go_perf_trace_enabled(False)
        assert go_perf_trace_enabled() is False
