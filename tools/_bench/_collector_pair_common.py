"""Shared helpers for Mac / Win collector-pair bench harnesses。

B3 (post-2026-05-29):pre-B3 ``run_mac_collector_pair.py`` (298 LOC) +
``run_win_collector_pair.py`` (352 LOC) 各自维护一份近字模相同的
parse-fps + aggregate + per-seed-detail logic(audit 低优 — Mac/Win
drift risk)。 抽出来:

- ``RE_GO`` / ``RE_PY``:perf-smoke stdout 的 fps 行 regex
- ``parse_fps_line(combined, test_node)``:从 subprocess output 找
  matching fps 行 + 解析成 metrics dict
- ``aggregate(runs)``:多 seed runs → mean ± std + CV summary dict
- ``classify_subprocess_result(rc, combined, dt)``:统一 SKIPPED /
  FAIL / TIMEOUT 分类 + 提示
- ``dump_runs_detail(lines, agg)``:per-seed detail markdown block

Mac/Win scripts 保留 backend-specific 执行层(local subprocess vs ssh)
+ cell-key 处理(Mac 用 int n_actors;Win 用 (n_actors, gomx, run_s)
3-tuple)+ markdown headline 表头。
"""

from __future__ import annotations

import re
from statistics import mean, stdev
from typing import Optional

# -----------------------------------------------------------------------------
# Regex — perf smoke stdout fps lines
# -----------------------------------------------------------------------------

# Go perf smoke: [perf smoke] elapsed=... fps=... fps/actor=... delta=...MB decode_errors=...
RE_GO = re.compile(
    r'\[perf smoke\]'
    r'.*?fps=(?P<fps>[\d.]+)'
    r'.*?fps/actor=(?P<fps_per_actor>[\d.]+)'
    r'.*?delta=(?P<mem_delta>[+-]?\d+)MB'
    r'.*?decode_errors=(?P<decode_errors>\d+)'
)

# Python mp perf smoke: [py-mp perf smoke] elapsed=... fps=... fps/actor=... delta=...MB
RE_PY = re.compile(
    r'\[py-mp perf smoke\]'
    r'.*?fps=(?P<fps>[\d.]+)'
    r'.*?fps/actor=(?P<fps_per_actor>[\d.]+)'
    r'.*?delta=(?P<mem_delta>[+-]?\d+)MB'
)


# -----------------------------------------------------------------------------
# Parse + classify
# -----------------------------------------------------------------------------


def parse_fps_line(combined: str, test_node: str, wall_s: float) -> Optional[dict]:
    """Find the fps line matching the test's backend regex,parse → metrics dict。

    Returns None if no matching line found (caller should log "PASS but no fps
    line — check test output format")。"""
    pattern = RE_GO if 'go' in test_node else RE_PY
    for line in combined.splitlines():
        m = pattern.search(line)
        if m:
            d = m.groupdict()
            result = {
                'fps': float(d['fps']),
                'fps_per_actor': float(d['fps_per_actor']),
                'mem_delta_mb': int(d['mem_delta']),
                'wall_s': round(wall_s, 1),
            }
            if 'decode_errors' in d:
                result['decode_errors'] = int(d['decode_errors'])
            return result
    return None


def classify_subprocess_failure(rc: int, combined: str) -> str:
    """Classify a non-zero pytest exit:'skipped' / 'fail'。 Caller prints
    diagnostic + returns None。 'skipped' = libs not built (acceptable);'fail'
    = real failure (print last 30 lines stderr)。"""
    if 'SKIPPED' in combined or 'no tests ran' in combined.lower():
        return 'skipped'
    return 'fail'


# -----------------------------------------------------------------------------
# Aggregate
# -----------------------------------------------------------------------------


def aggregate(runs: list[dict]) -> dict:
    """Mean ± std + CV (% of mean) per metric。 audit memory
    [[bench-variance-5seed-required]]:CV > 60% 需加 seed 到 robust;
    acceptance gate ≥ 5 seeds。"""
    if not runs:
        return {'n': 0}
    fps_vals = [r['fps'] for r in runs]
    fpa_vals = [r['fps_per_actor'] for r in runs]
    mem_vals = [r['mem_delta_mb'] for r in runs]
    fps_mean = mean(fps_vals)
    fps_std = stdev(fps_vals) if len(fps_vals) > 1 else 0.0
    fpa_mean = mean(fpa_vals)
    fpa_std = stdev(fpa_vals) if len(fpa_vals) > 1 else 0.0
    return {
        'n': len(runs),
        'fps_mean': round(fps_mean, 2),
        'fps_std': round(fps_std, 2),
        'fps_cv_pct': round(fps_std / fps_mean * 100, 1) if fps_mean else 0.0,
        'fps_per_actor_mean': round(fpa_mean, 2),
        'fps_per_actor_std': round(fpa_std, 2),
        'fps_per_actor_cv_pct': round(fpa_std / fpa_mean * 100, 1) if fpa_mean else 0.0,
        'mem_delta_mb_mean': round(mean(mem_vals), 0),
        'runs': runs,
    }


# -----------------------------------------------------------------------------
# Markdown rendering helpers
# -----------------------------------------------------------------------------


def format_headline_row(cell_label: str, backend: str, agg: dict) -> str:
    """One row of the headline summary table。 cell_label = Mac:'N=4' /
    Win:'N=4 GMP=1 T=15s' 等。"""
    if agg['n'] == 0:
        return f'| {cell_label} | {backend} | N/A | N/A | N/A | 0 |'
    fps_str = f'{agg["fps_mean"]:.2f} ± {agg["fps_std"]:.2f} ({agg["fps_cv_pct"]:.0f}%)'
    fpa_str = f'{agg["fps_per_actor_mean"]:.2f} ± {agg["fps_per_actor_std"]:.2f} ({agg["fps_per_actor_cv_pct"]:.0f}%)'
    mem_str = f'{agg["mem_delta_mb_mean"]:+.0f} MB'
    return f'| {cell_label} | {backend} | {fps_str} | {fpa_str} | {mem_str} | {agg["n"]} |'


def format_ratio_row(cell_label: str, go_agg: dict, py_agg: dict) -> str:
    """One row of the Go/Py ratio table。 'insufficient data' 若 either
    backend 没 data。"""
    if go_agg.get('n', 0) > 0 and py_agg.get('n', 0) > 0 and py_agg['fps_per_actor_mean'] > 0:
        ratio = go_agg['fps_per_actor_mean'] / py_agg['fps_per_actor_mean']
        interp = 'Go faster' if ratio > 1.0 else 'Python mp faster'
        return f'| {cell_label} | {ratio:.2f}x | {interp} |'
    return f'| {cell_label} | N/A | insufficient data |'


def dump_per_seed_detail(lines: list[str], backend: str, agg: dict) -> None:
    """Append per-seed detail bullets for one (cell, backend) pair。"""
    lines.append(f'**{backend}** (n={agg["n"]})')
    for i, r in enumerate(agg.get('runs', [])):
        lines.append(
            f'- seed {i + 1}: fps={r["fps"]:.2f} fps/actor={r["fps_per_actor"]:.2f} '
            f'mem_delta={r["mem_delta_mb"]:+d}MB wall={r["wall_s"]:.1f}s'
        )
    lines.append('')


def git_commit_short(repo_root) -> str:
    """Best-effort git short commit hash for markdown header。"""
    import subprocess as sp

    try:
        return sp.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=str(repo_root),
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        return 'unknown'
