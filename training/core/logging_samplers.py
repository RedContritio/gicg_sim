"""Resource sampler helpers for ``MetricsLogger`` — one-shot payload dicts。

Sampler kinds(自动起 daemon thread,周期写 metrics.jsonl):
- kind=mem:master/children RSS + torch.cuda alloc/reserved + host total/used +
  per-process ctx_switches / num_threads / num_fds / io_counters
- kind=cpu:per-core util %(psutil non-blocking)
- kind=gpu:nvidia-smi util/mem/temp/power/clocks(无 GPU graceful skip)
- kind=disk:system disk IO 累计 read/write bytes/count
- kind=net:system net IO 累计 bytes/packets sent/recv
- kind=load:Unix load avg 1m/5m/15m(Windows skip)

每个 ``_sample_*`` 是 callable → dict,thread 侧由
``training.core.logging_threads._ResourceSamplerThread`` 周期驱动,payload 交给
``MetricsLogger.log`` 落地。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tracemalloc

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
        # Python tracemalloc 跟踪的 master 进程 Python heap live alloc — 与
        # master_rss_mb 配对算 「非 Python heap 部分」(Go runtime + numpy/torch
        # native + libgicg.dylib + allocator caches)。 仅 tracemalloc 已 start
        # (e.g. via cfg.debug.mem_probe=true 由 tools._dev.mem_probe 启)时 sample,
        # production 默认 None — tracemalloc overhead 不强加给所有 run。
        'tracemalloc_total_mb': (
            round(tracemalloc.get_traced_memory()[0] / 1024**2, 1) if tracemalloc.is_tracing() else None
        ),
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
