"""mem_probe daemon thread + Go runtime stats integration smoke。

证明 mem_probe enable 后 _loop 实际 tick + 末尾打 Go stats 行。

实现注意:capfd 在 daemon thread 中抓 fd 2 的支持有限(pytest 在 test 入口
fork pipe,daemon thread 写 fd 2 是同进程同 fd,理论上 OK 但实测不稳)。
本测试改走「真把 sys.stderr 替换成 StringIO buffer」,daemon thread 用同一
Python sys.stderr 对象 → 同步可见(thread-safe — StringIO 写有 GIL 保护)。
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pytest


def _lib_built() -> bool:
    name = {'darwin': 'libgicg_actor.dylib', 'win32': 'libgicg_actor.dll'}.get(sys.platform, 'libgicg_actor.so')
    return (Path(__file__).resolve().parents[3] / 'gicg_env' / name).exists()


@pytest.mark.skipif(not _lib_built(), reason='libgicg_actor not built')
def test_mem_probe_emits_go_stats_line():
    """drive mem_probe 1s interval ~2.5s 跑,断言 stderr 含 Go stats 行 + 全字段。"""
    import tools._dev.mem_probe as mp

    if mp._THREAD is not None:
        pytest.skip('mem_probe already enabled in this process — cannot re-test in isolation')

    # 替 sys.stderr 为 StringIO buffer — daemon thread 的 print(..., file=sys.stderr)
    # 会同步写入同一对象(GIL 保护 StringIO.write 是 atomic)。
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

    captured = buf.getvalue()
    assert '[mem_probe t=' in captured, f'no tick output in stderr buffer:\n{captured}'
    assert '[mem_probe go] HeapAlloc=' in captured, f'Go stats line missing:\n{captured}'
    for field_name in (
        'HeapAlloc=',
        'HeapSys=',
        'HeapInuse=',
        'HeapIdle=',
        'HeapReleased=',
        'Sys=',
        'NumGC=',
        'PauseTotal=',
    ):
        assert field_name in captured, f'field {field_name!r} missing from Go stats line:\n{captured}'
