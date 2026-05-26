"""I29 T-C1 Mac fair bench harness — pure collector throughput (Go-actor vs Python mp)。

对 N ∈ {4, 8} 各跑 3 seeds × 2 backends × 15s window:
- test_go_actor_perf_smoke (Go-actor)
- test_python_mp_perf_smoke (Python mp)

通过 pytest 子进程调;抓 stdout 中的 fps 行;聚合 mean ± std;输出 markdown。

Usage:
    .venv/bin/python -m tools._bench.run_mac_collector_pair
    .venv/bin/python -m tools._bench.run_mac_collector_pair --n-actors 4 8 --seeds 3 --out tools/_bench/mac_collector_results.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean, stdev
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON = str(_REPO_ROOT / '.venv' / 'bin' / 'python')

# P2 acceptance: Go-subprocess path (I29 redesign,master 0 cgo) — replaces cgo
# perf_smoke node。 New test reads BENCH_N_ACTORS / BENCH_SEED env vars,supports
# arbitrary N (no hardcoded restriction)。
_GO_TEST = 'training/core/actor/tests/test_go_subprocess_perf_smoke.py::test_go_subprocess_perf_smoke_15s'
_PY_TEST = 'training/core/actor/tests/test_python_mp_perf_smoke.py::test_python_mp_perf_smoke_15s'

# Regex patterns for parsing stdout lines from each test
# Go: [perf smoke] elapsed=... fps=... fps/actor=... delta=...MB decode_errors=...
_RE_GO = re.compile(
    r'\[perf smoke\]'
    r'.*?fps=(?P<fps>[\d.]+)'
    r'.*?fps/actor=(?P<fps_per_actor>[\d.]+)'
    r'.*?delta=(?P<mem_delta>[+-]?\d+)MB'
    r'.*?decode_errors=(?P<decode_errors>\d+)'
)
# Python mp: [py-mp perf smoke] elapsed=... fps=... fps/actor=... delta=...MB
_RE_PY = re.compile(
    r'\[py-mp perf smoke\]'
    r'.*?fps=(?P<fps>[\d.]+)'
    r'.*?fps/actor=(?P<fps_per_actor>[\d.]+)'
    r'.*?delta=(?P<mem_delta>[+-]?\d+)MB'
)


def _run_one(test_node: str, n_actors: int, seed: int, timeout: int = 300) -> Optional[dict]:
    """Run one pytest test node via subprocess,返 parsed metrics dict or None。

    N_ACTORS / seed 通过环境变量注入:
    - BENCH_N_ACTORS — test 读取覆盖 N_ACTORS
    - BENCH_SEED — test 读取覆盖 seed
    """
    import os

    env = dict(os.environ)
    env['BENCH_N_ACTORS'] = str(n_actors)
    env['BENCH_SEED'] = str(seed)

    cmd = [
        _PYTHON,
        '-m',
        'pytest',
        test_node,
        '-s',  # no capture — see print output
        '-v',
        '--no-header',
        '--tb=short',
        '-m',
        'smoke_full',  # test nodes are marked smoke_full
    ]
    print(f'  [bench] running {test_node.split("::")[-1]} N={n_actors} seed={seed}', flush=True)
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            capture_output=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print(f'  [bench] TIMEOUT after {timeout}s', flush=True)
        return None
    dt = time.monotonic() - t0

    stdout = r.stdout
    stderr = r.stderr
    combined = stdout + stderr

    if r.returncode != 0:
        # SKIPPED (no libs) counts as None — not a failure
        if 'SKIPPED' in combined or 'no tests ran' in combined.lower():
            print(f'  [bench] SKIPPED (libs not built)', flush=True)
            return None
        print(f'  [bench] FAIL rc={r.returncode}', flush=True)
        # Print last portion of output for diagnosis
        for line in combined.splitlines()[-30:]:
            print(f'    {line}', flush=True)
        return None

    # Parse fps line from stdout
    pattern = _RE_GO if 'go' in test_node else _RE_PY
    for line in combined.splitlines():
        m = pattern.search(line)
        if m:
            d = m.groupdict()
            result = {
                'fps': float(d['fps']),
                'fps_per_actor': float(d['fps_per_actor']),
                'mem_delta_mb': int(d['mem_delta']),
                'wall_s': round(dt, 1),
            }
            if 'decode_errors' in d:
                result['decode_errors'] = int(d['decode_errors'])
            print(
                f'  [bench] OK fps={result["fps"]:.2f} fps/actor={result["fps_per_actor"]:.2f} '
                f'mem_delta={result["mem_delta_mb"]:+d}MB wall={dt:.1f}s',
                flush=True,
            )
            return result

    # If test passed but no fps line found
    print(f'  [bench] PASS but no fps line found — check test output format', flush=True)
    return None


def _aggregate(runs: list[dict]) -> dict:
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
        # CV (coefficient of variation, %) — std/mean*100。 audit memory
        # [[bench-variance-5seed-required]] 要求 explicit CV column 让 reader 直接
        # 看 variance,不必心算。 CV > 60% 需加 seed 到 robust。
        'fps_cv_pct': round(fps_std / fps_mean * 100, 1) if fps_mean else 0.0,
        'fps_per_actor_mean': round(fpa_mean, 2),
        'fps_per_actor_std': round(fpa_std, 2),
        'fps_per_actor_cv_pct': round(fpa_std / fpa_mean * 100, 1) if fpa_mean else 0.0,
        'mem_delta_mb_mean': round(mean(mem_vals), 0),
        'runs': runs,
    }


def _markdown_table(results: dict, out_path: Path) -> str:
    import subprocess as sp

    commit = sp.check_output(
        ['git', 'rev-parse', '--short', 'HEAD'],
        cwd=str(_REPO_ROOT),
        text=True,
    ).strip()
    date_str = time.strftime('%Y-%m-%d %H:%M')

    lines = [
        f'# I29 T-C1 Mac fair bench — pure collector throughput',
        f'',
        f'Commit: `{commit}`  ',
        f'Date: {date_str}  ',
        f'Window: 15s per run (same as Go-actor test)  ',
        f'',
        f'## Headline summary',
        f'',
        f'| N actors | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |',
        f'|----------|---------|---------------------|---------------------------|----------------|--------|',
    ]

    for n_actors, backends in sorted(results.items()):
        for backend, agg in backends.items():
            if agg['n'] == 0:
                lines.append(f'| {n_actors} | {backend} | N/A | N/A | N/A | 0 |')
                continue
            fps_str = f'{agg["fps_mean"]:.2f} ± {agg["fps_std"]:.2f} ({agg["fps_cv_pct"]:.0f}%)'
            fpa_str = f'{agg["fps_per_actor_mean"]:.2f} ± {agg["fps_per_actor_std"]:.2f} ({agg["fps_per_actor_cv_pct"]:.0f}%)'
            mem_str = f'{agg["mem_delta_mb_mean"]:+.0f} MB'
            lines.append(f'| {n_actors} | {backend} | {fps_str} | {fpa_str} | {mem_str} | {agg["n"]} |')

    lines += ['', '## Ratio (Go / Python mp)', '']
    lines += ['| N actors | fps/actor ratio | Interpretation |', '|----------|----------------|----------------|']
    for n_actors, backends in sorted(results.items()):
        go_agg = backends.get('go', {})
        py_agg = backends.get('python_mp', {})
        if go_agg.get('n', 0) > 0 and py_agg.get('n', 0) > 0 and py_agg['fps_per_actor_mean'] > 0:
            ratio = go_agg['fps_per_actor_mean'] / py_agg['fps_per_actor_mean']
            interp = 'Go faster' if ratio > 1.0 else 'Python mp faster'
            lines.append(f'| {n_actors} | {ratio:.2f}x | {interp} |')
        else:
            lines.append(f'| {n_actors} | N/A | insufficient data |')

    lines += ['', '## Per-seed detail', '']
    for n_actors, backends in sorted(results.items()):
        lines.append(f'### N={n_actors}')
        lines.append('')
        for backend, agg in backends.items():
            lines.append(f'**{backend}** (n={agg["n"]})')
            for i, r in enumerate(agg.get('runs', [])):
                lines.append(
                    f'- seed {i + 1}: fps={r["fps"]:.2f} fps/actor={r["fps_per_actor"]:.2f} '
                    f'mem_delta={r["mem_delta_mb"]:+d}MB wall={r["wall_s"]:.1f}s'
                )
            lines.append('')

    md = '\n'.join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding='utf-8')
    print(f'[bench] results dumped to {out_path}', flush=True)
    return md


def main() -> int:
    ap = argparse.ArgumentParser(description='I29 T-C1 Mac fair collector throughput bench')
    ap.add_argument('--n-actors', type=int, nargs='+', default=[4, 8])
    # default 5 (audit memory [[bench-variance-5seed-required]]:Mac M4 perf bench
    # 3-seed Go CV 100%+ misleading,seed outlier 让 mean 双向震荡。 5-seed CV
    # tighten 30-67% 后 robust。 acceptance gate 必 5-seed)。 --seeds 3 quick spot
    # check OK,production claim 必 ≥ 5。
    ap.add_argument('--seeds', type=int, default=5, help='number of seeds (1..seeds, default 5 per audit gate)')
    ap.add_argument('--out', type=str, default='tools/_bench/mac_collector_results.md')
    args = ap.parse_args()

    seed_list = list(range(1, args.seeds + 1))
    n_actors_list = args.n_actors
    out_path = _REPO_ROOT / args.out

    print(f'[bench] T-C1 Mac collector pair bench', flush=True)
    print(f'[bench] N_actors={n_actors_list} seeds={seed_list}', flush=True)
    print(f'[bench] total runs = {len(n_actors_list) * 2 * len(seed_list)} × ~15s window', flush=True)
    print(flush=True)

    # results[n_actors]['go'|'python_mp'] = list of run dicts
    results: dict[int, dict[str, list]] = {}

    for n_actors in n_actors_list:
        results[n_actors] = {'go': [], 'python_mp': []}
        print(f'[bench] === N={n_actors} ===', flush=True)
        for seed in seed_list:
            print(f'[bench] -- seed={seed} --', flush=True)
            # Go-subprocess (I29 redesign) — supports arbitrary N via BENCH_N_ACTORS
            r = _run_one(_GO_TEST, n_actors, seed)
            if r:
                results[n_actors]['go'].append(r)
            # Python mp
            r = _run_one(_PY_TEST, n_actors, seed)
            if r:
                results[n_actors]['python_mp'].append(r)
        print(flush=True)

    # Aggregate
    agg_results: dict = {}
    for n_actors, backends in results.items():
        agg_results[n_actors] = {}
        for backend, runs in backends.items():
            agg_results[n_actors][backend] = _aggregate(runs)

    # Print summary
    print('[bench] === SUMMARY ===', flush=True)
    for n_actors, backends in sorted(agg_results.items()):
        print(f'  N={n_actors}:', flush=True)
        for backend, agg in backends.items():
            if agg['n'] == 0:
                print(f'    {backend}: no data', flush=True)
            else:
                print(
                    f'    {backend}: fps/actor={agg["fps_per_actor_mean"]:.2f} ± {agg["fps_per_actor_std"]:.2f} '
                    f'(n={agg["n"]})',
                    flush=True,
                )
        go_agg = backends.get('go', {})
        py_agg = backends.get('python_mp', {})
        if go_agg.get('n', 0) > 0 and py_agg.get('n', 0) > 0 and py_agg['fps_per_actor_mean'] > 0:
            ratio = go_agg['fps_per_actor_mean'] / py_agg['fps_per_actor_mean']
            print(f'    ratio Go/Py = {ratio:.2f}x', flush=True)
    print(flush=True)

    # Dump markdown
    _markdown_table(agg_results, out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
