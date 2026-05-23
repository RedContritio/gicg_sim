"""Go runtime MemStats ctypes bridge — load + call + 基本字段断言。

不 spawn actor pool — 进程 ctypes.CDLL 加载 libgicg_actor 即有 Go runtime 在跑,
直接 ``runtime.ReadMemStats`` 可读非零 stats(go init goroutine + signal handler
等占据一定 heap)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _lib_built() -> bool:
    name = {'darwin': 'libgicg_actor.dylib', 'win32': 'libgicg_actor.dll'}.get(sys.platform, 'libgicg_actor.so')
    return (Path(__file__).resolve().parents[4] / 'gicg_env' / name).exists()


@pytest.mark.skipif(not _lib_built(), reason='libgicg_actor not built')
def test_read_go_mem_stats_returns_expected_keys_and_positive_sizes():
    """ctypes call returns dict with all expected keys + Sys >= HeapAlloc > 0。

    Sys 是 Go runtime 从 OS 拿的总 bytes,必须 >= HeapAlloc(live heap object bytes,
    HeapAlloc 仅是 Sys 的一部分)。 HeapAlloc > 0 因为 go init goroutine + signal
    handler 等占据 heap。
    """
    from training.core.actor.go_runtime_stats import read_go_mem_stats

    stats = read_go_mem_stats()

    expected_keys = {
        'heap_alloc_mb',
        'heap_sys_mb',
        'heap_inuse_mb',
        'heap_idle_mb',
        'heap_released_mb',
        'sys_mb',
        'mallocs',
        'frees',
        'num_gc',
        'pause_total_ns',
    }
    assert set(stats.keys()) == expected_keys, f'key drift: got {set(stats.keys())} expected {expected_keys}'

    # Go runtime 一旦加载即占 heap;Sys 必含 HeapSys + stack + GC metadata + ...
    assert stats['heap_alloc_mb'] > 0, f'HeapAlloc should be > 0 once Go runtime loaded, got {stats["heap_alloc_mb"]}'
    assert stats['sys_mb'] >= stats['heap_alloc_mb'], (
        f'Sys ({stats["sys_mb"]}MB) must be >= HeapAlloc ({stats["heap_alloc_mb"]}MB)'
    )
    # Mallocs 是累计计数(只增不减),Go runtime init 阶段已有大量 alloc。
    assert stats['mallocs'] > 0, f'Mallocs (cumulative count) should be > 0, got {stats["mallocs"]}'
    # Frees <= Mallocs (累计 free 数不可能超过累计 alloc 数)。
    assert stats['frees'] <= stats['mallocs'], f'Frees ({stats["frees"]}) must be <= Mallocs ({stats["mallocs"]})'
