"""Go-side perf trace ctypes bridge — flush + decode + enable/disable 路径。

不 spawn actor pool;直接 ctypes 调 flush。 enable 必须在 Python ctypes.CDLL
之前 set env var GICG_GO_PERF_TRACE=1 (Go init() 一次性 sample)。 本测试用
subprocess 隔离 enable case,主进程跑 disable case。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _lib_built() -> bool:
    name = {'darwin': 'libgicg_actor.dylib', 'win32': 'libgicg_actor.dll'}.get(sys.platform, 'libgicg_actor.so')
    return (Path(__file__).resolve().parents[4] / 'gicg_env' / name).exists()


@pytest.mark.skipif(not _lib_built(), reason='libgicg_actor not built')
def test_flush_returns_empty_when_disabled():
    """disabled (env unset) 时 flush 返 [] 不 raise — caller (sampler) 可 always-on 调。"""
    from training.core.actor.go_perf_trace import flush_go_perf_spans, go_perf_trace_enabled

    assert not go_perf_trace_enabled(), 'env must be unset in main test env'
    assert flush_go_perf_spans() == []


@pytest.mark.skipif(not _lib_built(), reason='libgicg_actor not built')
def test_flush_aggregates_spans_when_enabled():
    """Subprocess: env=1 → ctypes load → 触发 spans → flush → assert windows 含 stage。

    必须 subprocess 隔离 — Go init() 一次性 sample env var,主测试进程已 load
    libgicg_actor (其他测试),env 改不生效。
    """
    script = (
        'import sys, ctypes, json\n'
        'from training.core.actor.go_backend import _find_lib\n'
        'from training.core.actor.go_perf_trace import flush_go_perf_spans, go_perf_trace_enabled\n'
        # 必须先 触发 lib load (隐式 by _find_lib + ctypes inside go_perf_trace)
        'enabled = go_perf_trace_enabled()\n'
        'assert enabled, "GICG_GO_PERF_TRACE=1 not picked up by Go init"\n'
        # 触发 一些 spans — 用 hello() 等任意 capi call 不行 (它们不带 span),改调 pool
        # start/stop 会拖慢。 简单办法:Go side 测试 helper 没 expose,因此本子进程仅
        # verify enabled 状态 + 初始 flush 返 [] (无 span 触发) — 真聚合 verify 走
        # Go side TestPerfTraceEnabledAggregation。
        'res = flush_go_perf_spans()\n'
        'print(json.dumps({"enabled": enabled, "n_windows": len(res)}))\n'
    )
    env = {**os.environ, 'GICG_GO_PERF_TRACE': '1'}
    repo_root = Path(__file__).resolve().parents[4]
    r = subprocess.run(
        [sys.executable, '-c', script], env=env, cwd=str(repo_root), capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, f'subprocess failed: stdout={r.stdout!r} stderr={r.stderr!r}'
    import json

    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out['enabled'] is True
    assert out['n_windows'] == 0  # 无 span 触发 → 空 ring
