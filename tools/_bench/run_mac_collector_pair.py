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
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from tools._bench._collector_pair_common import (
    aggregate,
    classify_subprocess_failure,
    dump_per_seed_detail,
    format_headline_row,
    format_ratio_row,
    git_commit_short,
    parse_fps_line,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON = str(_REPO_ROOT / '.venv' / 'bin' / 'python')

# P2 acceptance: Go-subprocess path (I29 redesign,master 0 cgo) — replaces cgo
# perf_smoke node。 New test reads BENCH_N_ACTORS / BENCH_SEED env vars,supports
# arbitrary N (no hardcoded restriction)。
_GO_TEST = 'training/core/actor/tests/test_go_subprocess_perf_smoke.py::test_go_subprocess_perf_smoke_15s'
_PY_TEST = 'training/core/actor/tests/test_python_mp_perf_smoke.py::test_python_mp_perf_smoke_15s'


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

    combined = r.stdout + r.stderr

    if r.returncode != 0:
        kind = classify_subprocess_failure(r.returncode, combined)
        if kind == 'skipped':
            print(f'  [bench] SKIPPED (libs not built)', flush=True)
            return None
        print(f'  [bench] FAIL rc={r.returncode}', flush=True)
        for line in combined.splitlines()[-30:]:
            print(f'    {line}', flush=True)
        return None

    result = parse_fps_line(combined, test_node, wall_s=dt)
    if result is None:
        print(f'  [bench] PASS but no fps line found — check test output format', flush=True)
        return None
    print(
        f'  [bench] OK fps={result["fps"]:.2f} fps/actor={result["fps_per_actor"]:.2f} '
        f'mem_delta={result["mem_delta_mb"]:+d}MB wall={dt:.1f}s',
        flush=True,
    )
    return result


def _markdown_table(results: dict, out_path: Path) -> str:
    commit = git_commit_short(_REPO_ROOT)
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
        cell_label = str(n_actors)
        for backend, agg in backends.items():
            lines.append(format_headline_row(cell_label, backend, agg))

    lines += ['', '## Ratio (Go / Python mp)', '']
    lines += ['| N actors | fps/actor ratio | Interpretation |', '|----------|----------------|----------------|']
    for n_actors, backends in sorted(results.items()):
        lines.append(format_ratio_row(str(n_actors), backends.get('go', {}), backends.get('python_mp', {})))

    lines += ['', '## Per-seed detail', '']
    for n_actors, backends in sorted(results.items()):
        lines.append(f'### N={n_actors}')
        lines.append('')
        for backend, agg in backends.items():
            dump_per_seed_detail(lines, backend, agg)

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
            agg_results[n_actors][backend] = aggregate(runs)

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
