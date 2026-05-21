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


def _sample_cpu() -> dict:
    """One-shot per-core CPU util snapshot.

    psutil.cpu_percent 非阻塞模式(``interval=None``)需 prime — 第一次 call
    返 0%(无 baseline);_CpuSamplerThread.run() prime 后,后续每次 call
    返自 prev call 起的平均 utilization。
    """
    pct = psutil.cpu_percent(interval=None, percpu=True)
    return {
        'per_core_pct': [round(p, 1) for p in pct],
        'avg_pct': round(sum(pct) / len(pct), 1) if pct else 0.0,
        'max_pct': round(max(pct), 1) if pct else 0.0,
        'n_cores': len(pct),
    }


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


class _ResourceSamplerThread(threading.Thread):
    """Daemon thread emitting one ``kind=<kind>`` row per ``interval_s``。

    Generic sampler — `sample_fn` returns payload dict,thread logs via
    `logger.log(kind, payload)`。Uses ``Event.wait()`` (not ``sleep``) so
    ``stop()`` returns promptly on close instead of waiting up to a full
    interval。"""

    def __init__(
        self,
        logger: 'MetricsLogger',
        kind: str,
        interval_s: float,
        sample_fn,
        prime_fn=None,
    ) -> None:
        super().__init__(name=f'MetricsLogger{kind.capitalize()}Sampler', daemon=True)
        self._logger = logger
        self._kind = kind
        self._interval_s = interval_s
        self._sample_fn = sample_fn
        self._prime_fn = prime_fn
        self._stop_event = threading.Event()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=timeout)

    def run(self) -> None:
        if self._prime_fn is not None:
            try:
                self._prime_fn()
            except Exception:  # noqa: BLE001
                pass
        # Initial sample (so close-before-first-interval still emits ≥1 row).
        self._sample_once()
        while not self._stop_event.is_set():
            if self._stop_event.wait(self._interval_s):
                break
            self._sample_once()

    def _sample_once(self) -> None:
        try:
            payload = self._sample_fn()
        except Exception:  # noqa: BLE001 — sampler must never kill train
            return
        self._logger.log(self._kind, payload)


class MetricsLogger:
    """Append-only metrics writer。``close()`` flushes + closes handles +
    joins sampler threads。

    ``mem_sample_interval_s``:每 N 秒采一次 mem(master + children + cuda
    + host)写一行 kind="mem"。Default 10s。
    ``cpu_sample_interval_s``:每 N 秒采一次 per-core CPU util(psutil
    non-blocking 模式 + prime)写一行 kind="cpu"。Default 5s。
    任一 ``None`` / ``<=0`` 禁该 sampler(unit test 简化场景)。

    每行 ~250 B,长跑 train 容量微不足道,hotpath 不打扰(daemon thread)。
    """

    DEFAULT_MEM_INTERVAL_S = 10.0
    DEFAULT_CPU_INTERVAL_S = 5.0

    def __init__(
        self,
        artifacts_dir: Optional[Path],
        enable_tb: bool = True,
        mem_sample_interval_s: Optional[float] = None,
        cpu_sample_interval_s: Optional[float] = None,
    ) -> None:
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.enable_tb = enable_tb
        self._metrics_fh = None
        self._tb_writer = None
        self._t_start = time.perf_counter()
        self._write_lock = threading.Lock()
        self._samplers: list[_ResourceSamplerThread] = []

        if self.artifacts_dir is not None:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            self._metrics_fh = open(self.artifacts_dir / 'metrics.jsonl', 'a', encoding='utf-8')
            if enable_tb:
                try:
                    from torch.utils.tensorboard import SummaryWriter

                    self._tb_writer = SummaryWriter(log_dir=str(self.artifacts_dir / 'tb'))
                except ImportError:
                    self._tb_writer = None

        # Samplers after fh ready — write through self.log.
        if self._metrics_fh is not None:
            mem_iv = mem_sample_interval_s if mem_sample_interval_s is not None else self.DEFAULT_MEM_INTERVAL_S
            if mem_iv is not None and mem_iv > 0:
                t = _ResourceSamplerThread(self, 'mem', float(mem_iv), _sample_mem)
                self._samplers.append(t)
                t.start()
            cpu_iv = cpu_sample_interval_s if cpu_sample_interval_s is not None else self.DEFAULT_CPU_INTERVAL_S
            if cpu_iv is not None and cpu_iv > 0:
                # psutil.cpu_percent non-blocking needs prime call (returns 0 first time).
                t = _ResourceSamplerThread(
                    self,
                    'cpu',
                    float(cpu_iv),
                    _sample_cpu,
                    prime_fn=lambda: psutil.cpu_percent(interval=None, percpu=True),
                )
                self._samplers.append(t)
                t.start()

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
        # Stop samplers first so no concurrent write races the close().
        for s in self._samplers:
            s.stop()
        self._samplers.clear()
        if self._metrics_fh is not None:
            with self._write_lock:
                self._metrics_fh.close()
                self._metrics_fh = None
        if self._tb_writer is not None:
            self._tb_writer.close()
            self._tb_writer = None
