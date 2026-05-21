"""MetricsLogger — metrics.jsonl + optional TensorBoard.

Used by the pipeline driver. Each ``log_*`` method emits one jsonl row
+ optionally TB scalars. Caller passes the artifacts_dir at init.

Sampler kinds(自动起 daemon thread,周期写 metrics.jsonl):
- kind=mem:master/children RSS + torch.cuda alloc/reserved + host total/used +
  per-process ctx_switches / num_threads / num_fds / io_counters
- kind=cpu:per-core util %(psutil non-blocking)
- kind=gpu:nvidia-smi util/mem/temp/power/clocks(无 GPU graceful skip)
- kind=disk:system disk IO 累计 read/write bytes/count
- kind=net:system net IO 累计 bytes/packets sent/recv
- kind=load:Unix load avg 1m/5m/15m(Windows skip)

所有 paradigm 透明获益 — 上层 driver 不用关心。``close()`` 优雅停 + join。
任一 sampler interval 传 None 用 default,传 0/<=0 禁该 sampler。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import psutil


# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------


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


def _proc_info(p: psutil.Process) -> dict:
    """Per-process extended info — ctx_switches / num_threads / fds + IO.

    Windows ``num_fds`` 不存在,用 ``num_handles``;``io_counters`` 在
    Win + Unix 都有但 Linux 上需 process 可读 /proc/<pid>/io。失败的字段
    返 None(不阻塞采集其他)。
    """
    out: dict = {}
    try:
        cs = p.num_ctx_switches()
        out['ctx_switches_vol'] = cs.voluntary
        out['ctx_switches_invol'] = cs.involuntary
    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
        out['ctx_switches_vol'] = None
        out['ctx_switches_invol'] = None
    try:
        out['num_threads'] = p.num_threads()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        out['num_threads'] = None
    try:
        # Win: num_handles; Unix: num_fds.
        out['num_fds'] = p.num_handles() if sys.platform == 'win32' else p.num_fds()
    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
        out['num_fds'] = None
    try:
        io = p.io_counters()
        out['io_read_mb'] = round(io.read_bytes / 1024**2, 1)
        out['io_write_mb'] = round(io.write_bytes / 1024**2, 1)
    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, NotImplementedError):
        out['io_read_mb'] = None
        out['io_write_mb'] = None
    return out


def _sample_cpu() -> dict:
    """One-shot per-core CPU util snapshot.

    psutil.cpu_percent 非阻塞模式(``interval=None``)需 prime — 第一次 call
    返 0%(无 baseline);run() prime 后,后续每次 call 返自 prev call 起的
    平均 utilization。
    """
    pct = psutil.cpu_percent(interval=None, percpu=True)
    return {
        'per_core_pct': [round(p, 1) for p in pct],
        'avg_pct': round(sum(pct) / len(pct), 1) if pct else 0.0,
        'max_pct': round(max(pct), 1) if pct else 0.0,
        'n_cores': len(pct),
    }


def _sample_mem() -> dict:
    """One-shot mem snapshot — master RSS + children RSS + cuda + host +
    per-process ctx_switches / num_threads / num_fds / io_counters。

    Children 字段聚合 sum / max,详细 per-child list 不写(N=16 actor list
    每行 ~5 KB,放 metrics.jsonl 太肥)— 必要时离线脚本可读 children 进程
    list 自己扫。
    """
    me = psutil.Process(os.getpid())
    master_rss_mb = round(me.memory_info().rss / 1024**2, 1)
    master_info = _proc_info(me)

    children = me.children(recursive=True)
    child_rss_mbs = []
    child_threads = 0
    child_fds = 0
    child_io_read_mb = 0.0
    child_io_write_mb = 0.0
    child_ctx_vol = 0
    child_ctx_invol = 0
    for ch in children:
        try:
            child_rss_mbs.append(ch.memory_info().rss / 1024**2)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        info = _proc_info(ch)
        if info['num_threads'] is not None:
            child_threads += info['num_threads']
        if info['num_fds'] is not None:
            child_fds += info['num_fds']
        if info['io_read_mb'] is not None:
            child_io_read_mb += info['io_read_mb']
        if info['io_write_mb'] is not None:
            child_io_write_mb += info['io_write_mb']
        if info['ctx_switches_vol'] is not None:
            child_ctx_vol += info['ctx_switches_vol']
        if info['ctx_switches_invol'] is not None:
            child_ctx_invol += info['ctx_switches_invol']

    cuda_alloc_mb, cuda_reserved_mb = _torch_cuda_mem_mb()
    vm = psutil.virtual_memory()
    return {
        'master_pid': me.pid,
        'master_rss_mb': master_rss_mb,
        'master_num_threads': master_info['num_threads'],
        'master_num_fds': master_info['num_fds'],
        'master_ctx_vol': master_info['ctx_switches_vol'],
        'master_ctx_invol': master_info['ctx_switches_invol'],
        'master_io_read_mb': master_info['io_read_mb'],
        'master_io_write_mb': master_info['io_write_mb'],
        'children_count': len(child_rss_mbs),
        'children_rss_total_mb': round(sum(child_rss_mbs), 1),
        'children_rss_max_mb': round(max(child_rss_mbs), 1) if child_rss_mbs else 0.0,
        'children_num_threads_total': child_threads,
        'children_num_fds_total': child_fds,
        'children_ctx_vol_total': child_ctx_vol,
        'children_ctx_invol_total': child_ctx_invol,
        'children_io_read_mb': round(child_io_read_mb, 1),
        'children_io_write_mb': round(child_io_write_mb, 1),
        'cuda_alloc_mb': round(cuda_alloc_mb, 1),
        'cuda_reserved_mb': round(cuda_reserved_mb, 1),
        'host_used_mb': round(vm.used / 1024**2, 1),
        'host_total_mb': round(vm.total / 1024**2, 1),
    }


# Module-level — sampler thread 每次 call 跑 nvidia-smi subprocess。pynvml
# 替代会更快但多个依赖,subprocess 兼容性最好。
_NVIDIA_SMI_QUERY = (
    'utilization.gpu,utilization.memory,memory.used,memory.total,'
    'temperature.gpu,power.draw,fan.speed,clocks.gr,clocks.mem'
)


def _nvidia_smi_available() -> bool:
    return shutil.which('nvidia-smi') is not None


def _sample_gpu() -> dict:
    """One-shot GPU snapshot via nvidia-smi(per-device list)。

    无 nvidia-smi 直接 raise(_ResourceSamplerThread swallows + skips
    sampler effectively)— ctor 应该 _nvidia_smi_available 后才起 gpu
    sampler,这里不重 check,只 fail loud。
    """
    cmd = ['nvidia-smi', f'--query-gpu={_NVIDIA_SMI_QUERY}', '--format=csv,noheader,nounits']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        raise RuntimeError(f'nvidia-smi failed rc={r.returncode}: {r.stderr.strip()}')
    devices = []
    for line in r.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(',')]

        # 9 fields per _NVIDIA_SMI_QUERY。fan.speed 在某些卡(无风扇 / GTX
        # mobile)是 '[Not Supported]',float 转失败 → None。
        def _f(s: str):
            try:
                return float(s)
            except ValueError:
                return None

        devices.append(
            {
                'gpu_util_pct': _f(parts[0]),
                'mem_util_pct': _f(parts[1]),
                'mem_used_mb': _f(parts[2]),
                'mem_total_mb': _f(parts[3]),
                'temperature_c': _f(parts[4]),
                'power_w': _f(parts[5]),
                'fan_pct': _f(parts[6]),
                'clock_gr_mhz': _f(parts[7]),
                'clock_mem_mhz': _f(parts[8]),
            }
        )
    return {'devices': devices, 'n_devices': len(devices)}


def _sample_disk() -> dict:
    """System-wide disk IO 累计(自 boot)。delta 由 readers 算。"""
    io = psutil.disk_io_counters()
    if io is None:
        return {'read_mb': None, 'write_mb': None, 'read_count': None, 'write_count': None}
    return {
        'read_mb': round(io.read_bytes / 1024**2, 1),
        'write_mb': round(io.write_bytes / 1024**2, 1),
        'read_count': io.read_count,
        'write_count': io.write_count,
    }


def _sample_net() -> dict:
    """System-wide network IO 累计(自 boot)。"""
    io = psutil.net_io_counters()
    if io is None:
        return {'bytes_sent_mb': None, 'bytes_recv_mb': None, 'packets_sent': None, 'packets_recv': None}
    return {
        'bytes_sent_mb': round(io.bytes_sent / 1024**2, 1),
        'bytes_recv_mb': round(io.bytes_recv / 1024**2, 1),
        'packets_sent': io.packets_sent,
        'packets_recv': io.packets_recv,
    }


def _sample_load() -> dict:
    """Unix load avg 1m/5m/15m;Win 没此概念,os.getloadavg() AttributeError。"""
    if not hasattr(os, 'getloadavg'):
        raise OSError('load avg not supported on this platform')
    l1, l5, l15 = os.getloadavg()
    return {'load_1m': round(l1, 2), 'load_5m': round(l5, 2), 'load_15m': round(l15, 2)}


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


class _ResourceSamplerThread(threading.Thread):
    """Daemon thread emitting one ``kind=<kind>`` row per ``interval_s``。

    Generic sampler — ``sample_fn`` returns payload dict, thread logs via
    ``logger.log(kind, payload)``。 Uses ``Event.wait()`` (not ``sleep``) so
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
