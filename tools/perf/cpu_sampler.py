"""Lightweight per-core CPU utilization sampler via psutil.

Used alongside profile_actor/profile_train multi-process benchmarks
where typeperf / Get-Counter / WMI perf-data are blocked by user
group membership (Performance Log Users). psutil works as
non-admin.

Usage:

    python -m tools.perf.cpu_sampler <n_samples> <interval_s> <out_csv>

Outputs CSV with columns: t (epoch seconds), cpu0, cpu1, ..., cpuN.
First sample blocks for `interval_s` seconds (psutil baseline). Total
wall ~= n_samples * interval_s.
"""

from __future__ import annotations

import csv
import sys
import time

import psutil


def main() -> None:
    n_samples = int(sys.argv[1])
    interval = float(sys.argv[2])
    out_path = sys.argv[3]

    n_cores = psutil.cpu_count(logical=True)
    with open(out_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['t'] + [f'cpu{i}' for i in range(n_cores)])
        for _ in range(n_samples):
            pct = psutil.cpu_percent(interval=interval, percpu=True)
            w.writerow([f'{time.time():.3f}'] + [f'{x:.2f}' for x in pct])
            f.flush()


if __name__ == '__main__':
    main()
