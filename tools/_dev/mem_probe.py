"""master-process Python heap 分项 probe — cfg-driven tracemalloc + 周期采样。

启用方式:cfg ``[debug] mem_probe = true`` (post 2026-05-23 cfg-driven 改造,
旧 ``GICG_MEM_PROBE=1`` env var 已废)。 由 ``tools.runs._train.dispatch`` 在
paradigm dispatch 入口调 :func:`maybe_enable_from_cfg`,任何 paradigm 都通用。

**Scope 边界 — 不重复 metrics.jsonl** :master_rss / children_rss / cuda_alloc/
reserved / host_used 等 RSS 类字段已由 ``training/core/logging.py:_sample_mem``
采集进 ``metrics.jsonl`` 的 ``kind=mem`` record(psutil.Process().memory_info()
同源)。 production RSS trend 走 metrics。 此 probe 只补 metrics 没有的 **Python
heap 内部 alloc 分项归责**:`tracemalloc.statistics('filename')` 给每个 .py
源文件当前 live alloc 字节,delta 给「自上次采样以来增长最大文件」—— 这是定位
Python-side mem leak / wire decode 残留 / numpy view 钉 blob 等场景的不可替代
工具。

输出:每 `interval` 秒(默认 30s)向 stderr 打:
- tracemalloc 跟踪的总 Python alloc(MB)
- 按 source filename 聚合的 top-N 当前 alloc
- 自上次采样以来的 delta top-N(包谁在增长)

**与 metrics.jsonl 对照**:看 `master_rss_mb - tracemalloc_total_mb` 即「非
Python 部分」(Go runtime + numpy/torch native heap + libgicg.dylib + allocator
empty regions),据此 split Python leak vs native leak。

设计取舍:
- **filename 聚合而非 line 聚合**:line 维度对 Python container alloc 几乎全在
  ``collections/__init__.py:1234`` 一行,看不出 root cause。 filename 聚合
  把 alloc 归责到调用方文件。
- **tracemalloc 25 frame**:Python container 多 一层封装,< 10 frame 经常
  trace 不到调用方。
- **idempotent enable**:多次 import / 多次 enable 只启动一次 reporter
  thread(避免 fork / mp / pytest fixture 双注入)。
"""

from __future__ import annotations

import sys
import threading
import time
import tracemalloc
from typing import Any, Optional

_THREAD: Optional[threading.Thread] = None
_STOP_EVENT: Optional[threading.Event] = None


def enable_mem_probe(interval: int = 30, top_n: int = 15, frame_depth: int = 25) -> None:
    """启动 mem probe 后台线程。 调用多次只首次生效。

    Args:
        interval: 采样间隔秒数(默认 30s,适合 几分钟 short run)。
        top_n: top-N alloc 输出条数(默认 15)。
        frame_depth: tracemalloc 帧深度(默认 25)。
    """
    global _THREAD, _STOP_EVENT
    if _THREAD is not None:
        print('[mem_probe] already enabled — skipping re-enable', file=sys.stderr)
        return

    tracemalloc.start(frame_depth)
    start_ts = time.monotonic()
    last_snapshot: Optional[tracemalloc.Snapshot] = None
    _STOP_EVENT = threading.Event()

    # Lazy import — 在 enable_mem_probe 主线程内做(避免 daemon thread import 锁竞争
    # / pytest 下 thread import deadlock)。 import 失败(libgicg_actor 未 build)
    # 退化为 None,daemon thread 跑时 skip Go stats 行。
    try:
        from training.core.actor.go_runtime_stats import read_go_mem_stats as _read_go_stats
    except Exception as e:  # noqa: BLE001 — 任何 import 错都退化为「无 Go stats」
        _read_go_stats = None  # type: ignore[assignment]
        print(f'[mem_probe] Go runtime stats unavailable ({type(e).__name__}: {e}) — continuing', file=sys.stderr)
    try:
        from training.core.actor.go_perf_trace import flush_go_perf_spans as _flush_go_perf
    except Exception:  # noqa: BLE001 — lib 未 build 或 ctypes 错都退化为「无 Go perf」
        _flush_go_perf = None  # type: ignore[assignment]

    def _loop() -> None:
        nonlocal last_snapshot
        while not _STOP_EVENT.wait(interval):  # type: ignore[union-attr]
            now_ts = time.monotonic() - start_ts
            snap = tracemalloc.take_snapshot()
            stats = snap.statistics('filename')
            tm_total_mb = sum(s.size for s in stats) / 1024**2
            print(
                f'[mem_probe t={now_ts:6.0f}s] tracemalloc_total={tm_total_mb:7.0f}MB '
                f'(RSS / 非 Python heap 部分见 metrics.jsonl `kind=mem` record)',
                file=sys.stderr,
            )
            for st in stats[:top_n]:
                print(f'[mem_probe]   {st.size / 1024**2:7.1f}MB  {st.traceback[0]}', file=sys.stderr)
            if last_snapshot is not None:
                diff = snap.compare_to(last_snapshot, 'filename')
                diff.sort(key=lambda d: d.size_diff, reverse=True)
                print(f'[mem_probe] delta top {top_n}(自上次采样):', file=sys.stderr)
                for st in diff[:top_n]:
                    sign = '+' if st.size_diff >= 0 else ''
                    print(f'[mem_probe]   {sign}{st.size_diff / 1024**2:7.1f}MB  {st.traceback[0]}', file=sys.stderr)
            # Go runtime heap stats — split 出 Go side mem 增长 vs Python / native
            # (HeapAlloc 涨 = Go leak;HeapSys 涨 HeapAlloc 稳 = fragmentation;
            # 都稳但 RSS 涨 = 嫌疑在 native numpy/torch/libgicg)。
            if _read_go_stats is not None:
                try:
                    gs = _read_go_stats()
                    print(
                        f'[mem_probe go] HeapAlloc={gs["heap_alloc_mb"]:.1f}MB '
                        f'HeapSys={gs["heap_sys_mb"]:.1f}MB '
                        f'HeapInuse={gs["heap_inuse_mb"]:.1f}MB '
                        f'HeapIdle={gs["heap_idle_mb"]:.1f}MB '
                        f'HeapReleased={gs["heap_released_mb"]:.1f}MB '
                        f'Sys={gs["sys_mb"]:.1f}MB '
                        f'NumGC={gs["num_gc"]} '
                        f'PauseTotal={gs["pause_total_ns"] / 1e6:.1f}ms',
                        file=sys.stderr,
                    )
                except Exception as e:  # noqa: BLE001 — read 失败不让 probe 挂
                    print(f'[mem_probe go] read failed ({type(e).__name__}: {e})', file=sys.stderr)
            # Go-side perf trace top-3 by sum_ms — Go-actor 端 wall 分布 hot stages 速读
            # (production 详细数据见 metrics.jsonl `kind=go_perf` record)。
            if _flush_go_perf is not None:
                try:
                    wins = _flush_go_perf()
                    agg: dict[str, dict] = {}
                    for w in wins:
                        for n, st in w['stages'].items():
                            b = agg.setdefault(n, {'n': 0, 'sum_ms': 0.0})
                            b['n'] += st['n']
                            b['sum_ms'] += st['sum_ms']
                    top = sorted(agg.items(), key=lambda kv: -kv[1]['sum_ms'])[:3]
                    if top:
                        parts = [f'{n}(n={b["n"]} sum={b["sum_ms"]:.1f}ms)' for n, b in top]
                        print(f'[mem_probe go-perf] top-3: {" / ".join(parts)}', file=sys.stderr)
                except Exception as e:  # noqa: BLE001 — perf flush 失败不让 probe 挂
                    print(f'[mem_probe go-perf] read failed ({type(e).__name__}: {e})', file=sys.stderr)
            last_snapshot = snap
            sys.stderr.flush()

    _THREAD = threading.Thread(target=_loop, name='mem-probe', daemon=True)
    _THREAD.start()
    print(
        f'[mem_probe] enabled (interval={interval}s, top={top_n}, frames={frame_depth}) — '
        f'Python heap only; RSS via metrics.jsonl `kind=mem` record',
        file=sys.stderr,
    )


def maybe_enable_from_cfg(cfg: Any) -> None:
    """cfg ``[debug] mem_probe = true`` → :func:`enable_mem_probe`。 dispatch hook 入口。

    cfg.debug 缺失或 mem_probe=False 时 no-op。 配套字段:
    ``debug.mem_probe_interval_s`` (default 30) / ``debug.mem_probe_top_n`` (default 15)。"""
    dbg = getattr(cfg, 'debug', None)
    if dbg is None or not getattr(dbg, 'mem_probe', False):
        return
    interval = int(getattr(dbg, 'mem_probe_interval_s', 30))
    top_n = int(getattr(dbg, 'mem_probe_top_n', 15))
    enable_mem_probe(interval=interval, top_n=top_n)
