"""MetricsLogger — metrics.jsonl + optional TensorBoard.

Used by the pipeline driver. Each ``log_*`` method emits one jsonl row
+ optionally TB scalars. Caller passes the artifacts_dir at init.

Sampler helpers(``_sample_*`` / ``_nvidia_smi_available``)live in
``training.core.logging_samplers``;the daemon threads driving them live in
``training.core.logging_threads``。

所有 paradigm 透明获益 — 上层 driver 不用关心。``close()`` 优雅停 + join。
任一 sampler interval 传 None 用 default,传 0/<=0 禁该 sampler。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

import psutil

from training.core.logging_samplers import (
    _nvidia_smi_available,
    _sample_cpu,
    _sample_disk,
    _sample_gpu,
    _sample_load,
    _sample_mem,
    _sample_net,
)
from training.core.logging_threads import _QueueDrainerThread, _ResourceSamplerThread


# ---------------------------------------------------------------------------
# MetricsLogger
# ---------------------------------------------------------------------------


class MetricsLogger:
    """Append-only metrics writer。``close()`` flushes + closes handles +
    joins sampler threads。

    Sampler interval 参数(秒):
    - ``mem_sample_interval_s``        default 10
    - ``cpu_sample_interval_s``        default 5
    - ``gpu_sample_interval_s``        default 5(无 nvidia-smi auto-skip)
    - ``disk_sample_interval_s``       default 10
    - ``net_sample_interval_s``        default 10
    - ``load_sample_interval_s``       default 10(Win auto-skip)

    任一 ``None`` → 用 default。``0`` / 负数 → 禁该 sampler。每行 ~250 B-1 KB,
    长跑 train 容量微不足道,hotpath 不打扰(daemon thread)。
    """

    DEFAULT_MEM_INTERVAL_S = 10.0
    DEFAULT_CPU_INTERVAL_S = 5.0
    DEFAULT_GPU_INTERVAL_S = 5.0
    DEFAULT_DISK_INTERVAL_S = 10.0
    DEFAULT_NET_INTERVAL_S = 10.0
    DEFAULT_LOAD_INTERVAL_S = 10.0

    def __init__(
        self,
        artifacts_dir: Optional[Path],
        enable_tb: bool = True,
        mem_sample_interval_s: Optional[float] = None,
        cpu_sample_interval_s: Optional[float] = None,
        gpu_sample_interval_s: Optional[float] = None,
        disk_sample_interval_s: Optional[float] = None,
        net_sample_interval_s: Optional[float] = None,
        load_sample_interval_s: Optional[float] = None,
    ) -> None:
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.enable_tb = enable_tb
        self._metrics_fh = None
        self._tb_writer = None
        self._t_start = time.perf_counter()
        self._write_lock = threading.Lock()
        self._samplers: list[_ResourceSamplerThread] = []
        self._drainers: list[_QueueDrainerThread] = []

        if self.artifacts_dir is not None:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            self._metrics_fh = open(self.artifacts_dir / 'metrics.jsonl', 'a', encoding='utf-8')
            if enable_tb:
                try:
                    from torch.utils.tensorboard import SummaryWriter

                    self._tb_writer = SummaryWriter(log_dir=str(self.artifacts_dir / 'tb'))
                except ImportError:
                    self._tb_writer = None

        if self._metrics_fh is not None:
            self._maybe_start_sampler('mem', mem_sample_interval_s, self.DEFAULT_MEM_INTERVAL_S, _sample_mem)
            self._maybe_start_sampler(
                'cpu',
                cpu_sample_interval_s,
                self.DEFAULT_CPU_INTERVAL_S,
                _sample_cpu,
                prime_fn=lambda: psutil.cpu_percent(interval=None, percpu=True),
            )
            # GPU sampler only if nvidia-smi present.
            if _nvidia_smi_available():
                self._maybe_start_sampler('gpu', gpu_sample_interval_s, self.DEFAULT_GPU_INTERVAL_S, _sample_gpu)
            self._maybe_start_sampler('disk', disk_sample_interval_s, self.DEFAULT_DISK_INTERVAL_S, _sample_disk)
            self._maybe_start_sampler('net', net_sample_interval_s, self.DEFAULT_NET_INTERVAL_S, _sample_net)
            # Load avg only on Unix.
            if hasattr(os, 'getloadavg'):
                self._maybe_start_sampler('load', load_sample_interval_s, self.DEFAULT_LOAD_INTERVAL_S, _sample_load)

    def attach_callable_sampler(self, kind: str, interval_s: float, sample_fn) -> None:
        """Register a callable sampler + spawn a ``_ResourceSamplerThread`` daemon。

        ``sample_fn`` は callable returning a ``dict`` — same contract as internal
        ``_sample_mem`` / ``_sample_cpu`` etc。 Thread appended to ``self._samplers``
        so ``close()`` joins it automatically。

        No-op when ``self._metrics_fh is None`` (no artifacts_dir / test-disabled),
        matching the guard on ``attach_external_queue``。"""
        if self._metrics_fh is None:
            return
        t = _ResourceSamplerThread(self, kind, float(interval_s), sample_fn)
        self._samplers.append(t)
        t.start()

    def attach_external_queue(self, queue, name: str = 'external') -> None:
        """Register a cross-process queue + spawn a drainer thread。 子进程
        (e.g. InferenceServer)主动 push ``(kind, payload)`` tuple 到该
        queue,本 thread drain 并写入 metrics.jsonl(同 ``_write_lock`` 保护)。

        ``name`` 仅用于 thread name 调试,不影响 metrics.jsonl 内容(kind
        由 push 端决定)。"""
        if self._metrics_fh is None:
            return
        t = _QueueDrainerThread(self, queue, name=name)
        self._drainers.append(t)
        t.start()

    def _maybe_start_sampler(
        self,
        kind: str,
        user_interval: Optional[float],
        default_interval: float,
        sample_fn,
        prime_fn=None,
    ) -> None:
        iv = user_interval if user_interval is not None else default_interval
        if iv is None or iv <= 0:
            return
        t = _ResourceSamplerThread(self, kind, float(iv), sample_fn, prime_fn=prime_fn)
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
        # Stop samplers + drainers first so no concurrent write races the close().
        for s in self._samplers:
            s.stop()
        self._samplers.clear()
        for d in self._drainers:
            d.stop()
        self._drainers.clear()
        if self._metrics_fh is not None:
            with self._write_lock:
                self._metrics_fh.close()
                self._metrics_fh = None
        if self._tb_writer is not None:
            self._tb_writer.close()
            self._tb_writer = None
