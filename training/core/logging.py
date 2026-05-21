"""MetricsLogger — metrics.jsonl + optional TensorBoard.

Used by the pipeline driver. Each ``log_*`` method emits one jsonl row
+ optionally TB scalars. Caller passes the artifacts_dir at init.

Mem sampler: ctor 起 background daemon thread,周期 sample master +
所有子进程 RSS + torch.cuda mem,落 metrics.jsonl 一行 kind="mem"。
所有 paradigm 透明获益 — 上层 driver 不用关心。``close()`` 优雅停 +
join。``interval_s`` 可关(传 None / 0)。"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

import psutil


def _torch_cuda_mem_mb() -> tuple[float, float]:
    """Return (allocated_mb, reserved_mb) summed over all visible CUDA devices.

    Lazy import — CPU-only env (BC dataset / Mac CPU smoke) 不强制装 CUDA。
    """
    try:
        import torch
    except ImportError:
        return 0.0, 0.0
    if not torch.cuda.is_available():
        return 0.0, 0.0
    alloc = 0
    reserved = 0
    for i in range(torch.cuda.device_count()):
        alloc += torch.cuda.memory_allocated(i)
        reserved += torch.cuda.memory_reserved(i)
    return alloc / 1024**2, reserved / 1024**2


def _sample_mem() -> dict:
    """One-shot mem snapshot — master RSS + children RSS + cuda + host."""
    me = psutil.Process(os.getpid())
    master_rss_mb = round(me.memory_info().rss / 1024**2, 1)
    children = me.children(recursive=True)
    child_rss_mbs = []
    for ch in children:
        try:
            child_rss_mbs.append(ch.memory_info().rss / 1024**2)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    children_rss_total_mb = round(sum(child_rss_mbs), 1)
    children_rss_max_mb = round(max(child_rss_mbs), 1) if child_rss_mbs else 0.0
    cuda_alloc_mb, cuda_reserved_mb = _torch_cuda_mem_mb()
    vm = psutil.virtual_memory()
    return {
        'master_pid': me.pid,
        'master_rss_mb': master_rss_mb,
        'children_count': len(child_rss_mbs),
        'children_rss_total_mb': children_rss_total_mb,
        'children_rss_max_mb': children_rss_max_mb,
        'cuda_alloc_mb': round(cuda_alloc_mb, 1),
        'cuda_reserved_mb': round(cuda_reserved_mb, 1),
        'host_used_mb': round(vm.used / 1024**2, 1),
        'host_total_mb': round(vm.total / 1024**2, 1),
    }


class _MemSamplerThread(threading.Thread):
    """Daemon thread emitting one ``kind="mem"`` row per ``interval_s``。

    Uses ``Event.wait()`` (not ``sleep``) so ``stop()`` returns promptly
    on close instead of waiting up to a full interval。"""

    def __init__(self, logger: 'MetricsLogger', interval_s: float) -> None:
        super().__init__(name='MetricsLoggerMemSampler', daemon=True)
        self._logger = logger
        self._interval_s = interval_s
        self._stop_event = threading.Event()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=timeout)

    def run(self) -> None:
        # Initial sample (so close-before-first-interval still emits ≥1 row).
        self._sample_once()
        while not self._stop_event.is_set():
            if self._stop_event.wait(self._interval_s):
                break
            self._sample_once()

    def _sample_once(self) -> None:
        try:
            payload = _sample_mem()
        except Exception:  # noqa: BLE001 — sampler must never kill train
            return
        self._logger.log('mem', payload)


class MetricsLogger:
    """Append-only metrics writer。``close()`` flushes + closes handles +
    joins mem sampler thread。

    ``mem_sample_interval_s``:每 N 秒采一次 mem(master + children + cuda
    + host)写一行 kind="mem"。``None`` / ``<=0`` 关 sampler(对一些
    unit test 简化场景有用)。 Default 10s — 长跑 train 可见每 minute ~6 行
    mem 数据,容量微不足道(每行 ~250 B),hotpath 不打扰(daemon thread)。
    """

    DEFAULT_MEM_INTERVAL_S = 10.0

    def __init__(
        self,
        artifacts_dir: Optional[Path],
        enable_tb: bool = True,
        mem_sample_interval_s: Optional[float] = None,
    ) -> None:
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.enable_tb = enable_tb
        self._metrics_fh = None
        self._tb_writer = None
        self._t_start = time.perf_counter()
        self._write_lock = threading.Lock()
        self._mem_sampler: Optional[_MemSamplerThread] = None

        if self.artifacts_dir is not None:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            self._metrics_fh = open(self.artifacts_dir / 'metrics.jsonl', 'a', encoding='utf-8')
            if enable_tb:
                try:
                    from torch.utils.tensorboard import SummaryWriter

                    self._tb_writer = SummaryWriter(log_dir=str(self.artifacts_dir / 'tb'))
                except ImportError:
                    self._tb_writer = None

        # Start mem sampler after fh ready — needs to write through self.log.
        interval = mem_sample_interval_s if mem_sample_interval_s is not None else self.DEFAULT_MEM_INTERVAL_S
        if self._metrics_fh is not None and interval is not None and interval > 0:
            self._mem_sampler = _MemSamplerThread(self, float(interval))
            self._mem_sampler.start()

    def log(self, kind: str, payload: dict) -> None:
        """Append one row to metrics.jsonl with ``kind`` + payload +
        wall_seconds for cross-row alignment. Thread-safe."""
        if self._metrics_fh is None:
            return
        row = {'kind': kind, 'wall_s': round(time.perf_counter() - self._t_start, 3), **payload}
        line = json.dumps(row, ensure_ascii=False) + '\n'
        with self._write_lock:
            self._metrics_fh.write(line)
            self._metrics_fh.flush()

    def log_iter(self, state, breakdown: dict) -> None:
        self.log(
            'iter',
            {
                'step': state.step,
                'frames': state.total_transitions,
                'episodes': state.total_episodes,
                'train_steps': state.train_steps,
                **breakdown,
            },
        )

    def log_eval(self, state, report) -> None:
        """Log an EvalReport-like object. Accepts dict for plain values."""
        if hasattr(report, '__dataclass_fields__'):
            from dataclasses import asdict

            r = asdict(report)
        else:
            r = dict(report)
        self.log('eval', {'step': state.step, **r})

    def add_scalar(self, tag: str, value: float, step: int) -> None:
        if self._tb_writer is not None:
            self._tb_writer.add_scalar(tag, value, step)

    def close(self) -> None:
        # Stop sampler first so no concurrent write races the close().
        if self._mem_sampler is not None:
            self._mem_sampler.stop()
            self._mem_sampler = None
        if self._metrics_fh is not None:
            with self._write_lock:
                self._metrics_fh.close()
                self._metrics_fh = None
        if self._tb_writer is not None:
            self._tb_writer.close()
            self._tb_writer = None
