"""Go runtime heap stats — Python ctypes 读 libgicg_actor 的 ``runtime.MemStats``。

用途:mem leak 定位的「第二象限」。 master process 长跑 RSS 单调涨(metrics.jsonl
``master_rss_mb``),但 Python heap (``tracemalloc``) 不增 → 嫌疑在 Go runtime
heap 或 native allocator(numpy/torch backend / libgicg_actor 内部 buffer)。
本模块给出 Go runtime 侧的 heap account,据此 split:

- ``HeapAlloc`` 涨 → Go side leak(actor goroutine 持续 alloc 不放)
- ``HeapAlloc`` 稳但 ``HeapSys`` 涨 → fragmentation(返回 OS 慢)
- ``HeapAlloc`` + ``HeapSys`` 都稳但 RSS 涨 → 嫌疑在 native(numpy/torch/libgicg
  自身),Go 侧无锅

字段语义(``runtime.MemStats`` godoc 简化版):

- ``HeapAlloc``:当前 live heap object bytes(Go GC 视角下的「活内存」)
- ``HeapSys``:从 OS 拿过来的 heap-region bytes(含 in-use + idle + released)
- ``HeapInuse``:in-use span bytes(含 fragmentation,>= HeapAlloc)
- ``HeapIdle``:idle span bytes(分配过、当前空闲,可还 OS)
- ``HeapReleased``:已用 madvise 还 OS 的 bytes(virtual 还在,物理已释)
- ``Sys``:整个 Go runtime 从 OS 拿的总 bytes(heap + stack + GC 元数据 + ...)
- ``Mallocs`` / ``Frees``:累计 alloc / free object 计数,``Mallocs - Frees`` = 当前活对象数
- ``NumGC``:已完成 GC 周期数
- ``PauseTotalNs``:累计 stop-the-world ns

调用开销:``runtime.ReadMemStats`` 是 stop-the-world,微秒级 — mem_probe 30s 一次
采样可接受;不要在 hot path 调。

边界:本模块不 spawn pool — 进程一旦 ``ctypes.CDLL(libgicg_actor)`` 即有 Go runtime
在跑(go init goroutine + signal handler),即可读到非零 stats。 lib 未 build / 找不到
→ raise FileNotFoundError(reuse ``go_backend._find_lib`` 同一路径解析)。
"""

from __future__ import annotations

import ctypes
from typing import Any

from training.core.actor.go_backend import _find_lib


class _GoRuntimeMemStats(ctypes.Structure):
    """C struct 同构 — 字段顺序 / 类型必须与 gicg_actor/capi/main.go GoRuntimeMemStats 一致。

    任一端加字段必须同步更新另一端,否则 ctypes 按 padding 解读会读到错位 / garbage。
    """

    _fields_ = [
        ('heap_alloc', ctypes.c_uint64),
        ('heap_sys', ctypes.c_uint64),
        ('heap_inuse', ctypes.c_uint64),
        ('heap_idle', ctypes.c_uint64),
        ('heap_released', ctypes.c_uint64),
        ('sys', ctypes.c_uint64),
        ('mallocs', ctypes.c_uint64),
        ('frees', ctypes.c_uint64),
        ('num_gc', ctypes.c_uint64),
        ('pause_total_ns', ctypes.c_uint64),
    ]


_LIB: ctypes.CDLL | None = None


def _load() -> ctypes.CDLL:
    """Lazy-load libgicg_actor + bind ``gicg_actor_runtime_memstats`` 签名。 缓存 handle。"""
    global _LIB
    if _LIB is None:
        lib = ctypes.CDLL(str(_find_lib()))
        lib.gicg_actor_runtime_memstats.restype = ctypes.c_int
        lib.gicg_actor_runtime_memstats.argtypes = [ctypes.POINTER(_GoRuntimeMemStats)]
        _LIB = lib
    return _LIB


def read_go_mem_stats() -> dict[str, Any]:
    """读 Go runtime MemStats,返字典。

    size 类字段(``heap_alloc`` / ``heap_sys`` / ``heap_inuse`` / ``heap_idle`` /
    ``heap_released`` / ``sys``)单位转 MB(float);count 类字段(``mallocs`` /
    ``frees`` / ``num_gc`` / ``pause_total_ns``)保留原值(int)。

    Returns:
        dict 含 10 个 key — 6 个 ``_mb`` size 字段(float)+ 4 个原值 count 字段(int)。

    Raises:
        FileNotFoundError: libgicg_actor 未 build / 找不到(走 ``_find_lib``)。
        RuntimeError: C func 返非 0(nil out pointer,理论上不会发生)。
    """
    lib = _load()
    out = _GoRuntimeMemStats()
    rc = int(lib.gicg_actor_runtime_memstats(ctypes.byref(out)))
    if rc != 0:
        raise RuntimeError(f'gicg_actor_runtime_memstats failed: rc={rc}')
    mb = 1024.0 * 1024.0
    return {
        'heap_alloc_mb': out.heap_alloc / mb,
        'heap_sys_mb': out.heap_sys / mb,
        'heap_inuse_mb': out.heap_inuse / mb,
        'heap_idle_mb': out.heap_idle / mb,
        'heap_released_mb': out.heap_released / mb,
        'sys_mb': out.sys / mb,
        'mallocs': int(out.mallocs),
        'frees': int(out.frees),
        'num_gc': int(out.num_gc),
        'pause_total_ns': int(out.pause_total_ns),
    }
