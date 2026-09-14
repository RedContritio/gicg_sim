"""mem_probe daemon thread + Python heap reporting integration smoke。

证明 mem_probe enable 后 _loop 实际 tick + Python heap 分项 + cfg-driven
maybe_enable_from_cfg 入口正确读 cfg.debug 字段。

实现注意:capfd 在 daemon thread 中抓 fd 2 的支持有限(pytest 在 test 入口
fork pipe,daemon thread 写 fd 2 是同进程同 fd,理论上 OK 但实测不稳)。
本测试改走「真把 sys.stderr 替换成 StringIO buffer」,daemon thread 用同一
Python sys.stderr 对象 → 同步可见(thread-safe — StringIO 写有 GIL 保护)。
"""

from __future__ import annotations

import io
import sys
import time
import tracemalloc

import pytest


def test_maybe_enable_from_cfg_no_op_when_disabled():
    """cfg.debug.mem_probe=False (default) → maybe_enable_from_cfg no-op:_THREAD 仍 None。

    必须先于 enable smoke 跑 — 后者一旦 enable,本 process _THREAD 单例化无法回退。
    """
    import tools._dev.mem_probe as mp
    from training.core.config.base import DebugCfg

    if mp._THREAD is not None:
        pytest.skip('mem_probe already enabled in this process')

    class _Cfg:
        debug = DebugCfg()  # mem_probe=False default

    mp.maybe_enable_from_cfg(_Cfg())
    assert mp._THREAD is None, 'mem_probe must stay disabled when cfg.debug.mem_probe=False'


def test_maybe_enable_from_cfg_missing_debug_no_op():
    """cfg 无 debug attr (mock 对象) → silent no-op,不 raise。 同上先跑。"""
    import tools._dev.mem_probe as mp

    if mp._THREAD is not None:
        pytest.skip('mem_probe already enabled in this process')

    class _Cfg:
        pass

    mp.maybe_enable_from_cfg(_Cfg())
    assert mp._THREAD is None


def test_mem_probe_emits_python_heap_lines():
    """drive mem_probe 1s interval ~2.5s 跑,断言 stderr 含 Python heap 总量、来源与增量。"""
    import tools._dev.mem_probe as mp

    if mp._THREAD is not None:
        pytest.skip('mem_probe already enabled in this process — cannot re-test in isolation')

    # 替 sys.stderr 为 StringIO buffer — daemon thread 的 print(..., file=sys.stderr)
    # 会同步写入同一对象(GIL 保护 StringIO.write 是 atomic)。
    was_tracing = tracemalloc.is_tracing()
    real_stderr = sys.stderr
    buf = io.StringIO()
    sys.stderr = buf
    try:
        mp.enable_mem_probe(interval=1, top_n=3, frame_depth=10)
        # 等 ~2.5s → 至少 2 个 tick(首在 t=1s,二在 t=2s)。
        time.sleep(2.5)
    finally:
        if mp._STOP_EVENT is not None:
            mp._STOP_EVENT.set()
        if mp._THREAD is not None:
            mp._THREAD.join(timeout=2.0)
        sys.stderr = real_stderr
        mp._THREAD = None
        mp._STOP_EVENT = None
        if not was_tracing:
            tracemalloc.stop()

    captured = buf.getvalue()
    assert '[mem_probe t=' in captured, f'no tick output in stderr buffer:\n{captured}'
    assert 'tracemalloc_total=' in captured
    assert 'mem_probe.py:' in captured
    assert 'delta top 3' in captured
    assert '[mem_probe go]' not in captured  # Go runtime now belongs to actor subprocesses.
