"""Per-interval psutil sampler for training runs."""

from __future__ import annotations

import os
import threading


def system_monitor_loop(
    log,
    stop_event: threading.Event,
    interval_s: float,
) -> None:
    """Every ``interval_s`` seconds, sample CPU / mem / load and emit a
    ``system`` event. Silently no-op if psutil isn't installed."""
    try:
        import psutil
    except ImportError:
        return
    proc = psutil.Process()
    psutil.cpu_percent(interval=None)
    while not stop_event.wait(interval_s):
        try:
            cpu = psutil.cpu_percent(interval=None)
            vm = psutil.virtual_memory()
            rss = proc.memory_info().rss
            try:
                load1 = os.getloadavg()[0]
            except (OSError, AttributeError):
                load1 = -1.0
            log(
                'system',
                {
                    'cpu_pct': round(cpu, 1),
                    'mem_used_gb': round(vm.used / 1e9, 2),
                    'rss_mb': round(rss / 1e6, 1),
                    'load1': round(load1, 2),
                },
            )
        except Exception:
            continue
