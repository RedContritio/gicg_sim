"""Win box fair bench — ssh-dispatched pytest perf_smoke sweep。

Mirror tools/_bench/run_mac_collector_pair.py 但走 ssh 到 Win box (dev@192.168.31.56,
cfg-driven via cfg.toml [meta].host=remote)。

Each sweep cell = 1 pytest spawn (`test_go_subprocess_perf_smoke_15s` 或
`test_python_mp_perf_smoke_15s`) on Win,with BENCH_N_ACTORS + BENCH_SEED env var。
Parse stdout fps line + aggregate。

Usage:
    .venv/bin/python -m tools._bench.run_win_collector_pair \
        --n-actors 4 8 16 24 --seeds 3 --out tools/_bench/p2_results/sweep_win.md

Each pytest spawn ~15s + setup overhead;5 seeds × 4 N × 2 backend = 40 spawn ×
~20s wall (parallel batch=1 因 Win box single GPU + InfServer port conflict)。
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

# Win box (cfg-driven via bench cfg [meta].host=remote)。
_WIN_SSH = 'dev@192.168.31.56'
_WIN_ROOT = 'D:/gicg_dev'

_GO_TEST = 'training/core/actor/tests/test_go_subprocess_perf_smoke.py::test_go_subprocess_perf_smoke_15s'
_PY_TEST = 'training/core/actor/tests/test_python_mp_perf_smoke.py::test_python_mp_perf_smoke_15s'


def _ssh_pytest(
    test_node: str,
    n_actors: int,
    seed: int,
    *,
    gomaxprocs: Optional[int] = None,
    run_seconds: Optional[float] = None,
    timeout: int = 300,
) -> Optional[dict]:
    """SSH dispatch single pytest spawn on Win box,parse stdout fps。"""
    test_name = test_node.split('::')[-1]
    tag = f'N={n_actors} seed={seed}'
    if gomaxprocs is not None:
        tag += f' GOMAXPROCS={gomaxprocs}'
    if run_seconds is not None:
        tag += f' T={run_seconds:.0f}s'
    print(f'  [bench] running {test_name} {tag}', flush=True)

    # Build PowerShell cmd:cd D:/gicg_dev + venv python + env var inline + pytest invocation
    env_lines = [
        f'$env:BENCH_N_ACTORS={n_actors}',
        f'$env:BENCH_SEED={seed}',
    ]
    if gomaxprocs is not None:
        env_lines.append(f'$env:BENCH_GOMAXPROCS={gomaxprocs}')
    if run_seconds is not None:
        env_lines.append(f'$env:BENCH_RUN_SECONDS={run_seconds}')
    ps_cmd = (
        f'cd {_WIN_ROOT}; ' + '; '.join(env_lines) + '; '
        f'.\\.venv\\Scripts\\python.exe -m pytest {test_node} -s -v --no-header --tb=short -m smoke_full'
    )

    # Dynamic timeout — longer run_seconds 需要更大 ssh timeout (bootstrap ~5s + window + drain + setup margin)。
    effective_timeout = timeout
    if run_seconds is not None:
        effective_timeout = max(timeout, int(run_seconds * 6 + 120))

    t0 = time.monotonic()
    try:
        # binary mode + decode with errors='replace' — Win PowerShell stderr 含 GBK
        # 编码字符 (e.g. 中文 process kill 错误消息),UTF-8 strict decode fail。 replace
        # 让 bench harness 不撞 codec error。
        r = subprocess.run(
            ['ssh', _WIN_SSH, f'powershell -c "{ps_cmd}"'],
            capture_output=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired:
        print(f'  [bench] TIMEOUT after {timeout}s', flush=True)
        return None
    dt = time.monotonic() - t0

    stdout_text = (r.stdout or b'').decode('utf-8', errors='replace')
    stderr_text = (r.stderr or b'').decode('utf-8', errors='replace')
    combined = stdout_text + stderr_text

    if r.returncode != 0:
        kind = classify_subprocess_failure(r.returncode, combined)
        if kind == 'skipped':
            print(f'  [bench] SKIPPED (libs not built)', flush=True)
            return None
        print(f'  [bench] FAIL rc={r.returncode} wall={dt:.1f}s', flush=True)
        for line in combined.splitlines()[-30:]:
            print(f'    {line}', flush=True)
        return None

    result = parse_fps_line(combined, test_node, wall_s=dt)
    if result is None:
        print(f'  [bench] PASS but no fps line — output 前 30 行:', flush=True)
        for line in combined.splitlines()[:30]:
            print(f'    {line}', flush=True)
        return None
    print(
        f'  [bench] OK fps={result["fps"]:.2f} fps/actor={result["fps_per_actor"]:.2f} '
        f'mem_delta={result["mem_delta_mb"]:+d}MB wall={dt:.1f}s',
        flush=True,
    )
    return result


def _cell_label(cell_key) -> str:
    """cell_key = (n_actors, gomx_or_None, run_s_or_None)。 出标签只含非 None 维度。"""
    if isinstance(cell_key, tuple):
        n, gomx, run_s = cell_key
        parts = [f'N={n}']
        if gomx is not None:
            parts.append(f'G={gomx}')
        if run_s is not None:
            parts.append(f'T={run_s:.0f}s')
        return ' '.join(parts)
    return f'N={cell_key}'


def _sort_cell_key(kv) -> tuple:
    """Sort key handles None — None → -1 for stable order across mixed sweeps。"""
    key = kv[0]
    if isinstance(key, tuple):
        n, gomx, run_s = key
        return (n, gomx if gomx is not None else -1, run_s if run_s is not None else -1.0)
    return (key, -1, -1.0)


def _markdown_table(results: dict, out_path: Path) -> str:
    commit = git_commit_short(_REPO_ROOT)
    date_str = time.strftime('%Y-%m-%d %H:%M')

    lines = [
        f'# I29 Win box fair bench — pure collector throughput',
        f'',
        f'Commit: `{commit}`',
        f'Date: {date_str}',
        f'Box: {_WIN_SSH} (DESKTOP-GHJCC7Q, 5070 Ti + 9950X3D)',
        f'Window: 15s per run',
        f'',
        f'## Headline summary',
        f'',
        f'| Cell | Backend | fps mean ± std (CV) | fps/actor mean ± std (CV) | mem_delta mean | n runs |',
        f'|------|---------|---------------------|---------------------------|----------------|--------|',
    ]

    for cell_key, backends in sorted(results.items(), key=_sort_cell_key):
        cell_label = _cell_label(cell_key)
        for backend, agg in backends.items():
            lines.append(format_headline_row(cell_label, backend, agg))

    lines += ['', '## Ratio (Go / Python mp)', '']
    lines += ['| Cell | fps/actor ratio | Interpretation |', '|------|----------------|----------------|']
    for cell_key, backends in sorted(results.items(), key=_sort_cell_key):
        lines.append(format_ratio_row(_cell_label(cell_key), backends.get('go', {}), backends.get('python_mp', {})))

    lines += ['', '## Per-seed detail', '']
    for cell_key, backends in sorted(results.items(), key=_sort_cell_key):
        cell_label = _cell_label(cell_key)
        lines.append(f'### {cell_label}')
        lines.append('')
        for backend, agg in backends.items():
            dump_per_seed_detail(lines, backend, agg)

    md = '\n'.join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding='utf-8')
    print(f'[bench] results dumped to {out_path}', flush=True)
    return md


def main() -> int:
    ap = argparse.ArgumentParser(
        description='I29 Win box fair collector throughput bench (ssh-dispatched pytest sweep)'
    )
    ap.add_argument('--n-actors', type=int, nargs='+', default=[4, 8, 16])
    ap.add_argument('--seeds', type=int, default=3, help='number of seeds (1..seeds, default 3 for cost)')
    ap.add_argument(
        '--gomaxprocs',
        type=int,
        nargs='+',
        default=None,
        help='Go GOMAXPROCS sweep values (None = use default = 1, post-D6)。 typical: 1 2 4',
    )
    ap.add_argument(
        '--run-seconds',
        type=float,
        nargs='+',
        default=None,
        help='RUN_SECONDS sweep values (None = test default 15.0)。 typical: 15 30 60',
    )
    ap.add_argument('--out', type=str, default='tools/_bench/p2_results/sweep_win.md')
    ap.add_argument(
        '--backend',
        choices=['go', 'python_mp', 'both'],
        default='both',
        help='which backend(s) to sweep (default: both)',
    )
    args = ap.parse_args()

    seed_list = list(range(1, args.seeds + 1))
    out_path = _REPO_ROOT / args.out

    backends_to_run = []
    if args.backend in ('go', 'both'):
        backends_to_run.append(('go', _GO_TEST))
    if args.backend in ('python_mp', 'both'):
        backends_to_run.append(('python_mp', _PY_TEST))

    print(f'[bench] Win collector pair sweep', flush=True)
    print(f'[bench] N_actors={args.n_actors} seeds={seed_list} backends={[b for b, _ in backends_to_run]}', flush=True)
    print(f'[bench] total runs = {len(args.n_actors) * len(backends_to_run) * len(seed_list)} × ~30s wall', flush=True)
    print(flush=True)

    # GOMAXPROCS / run_seconds sweep — None 表示用 default,sweep 多值 = bench grid
    gomaxprocs_list = args.gomaxprocs if args.gomaxprocs else [None]
    run_seconds_list = args.run_seconds if args.run_seconds else [None]

    # cell_key = (n_actors, gomx_or_None, run_s_or_None) 统一 3-tuple。 _cell_label 出非 None 维度。
    flat_results: dict = {}
    for n_actors in args.n_actors:
        for gomaxprocs in gomaxprocs_list:
            for run_s in run_seconds_list:
                cell_key = (n_actors, gomaxprocs, run_s)
                flat_results[cell_key] = {b: [] for b, _ in backends_to_run}
                cell_tag = f'N={n_actors}'
                if gomaxprocs is not None:
                    cell_tag += f' GOMAXPROCS={gomaxprocs}'
                if run_s is not None:
                    cell_tag += f' T={run_s:.0f}s'
                print(f'[bench] === {cell_tag} ===', flush=True)
                for seed in seed_list:
                    print(f'[bench] -- seed={seed} --', flush=True)
                    for backend_name, test_node in backends_to_run:
                        gomx = gomaxprocs if backend_name == 'go' else None
                        r = _ssh_pytest(test_node, n_actors, seed, gomaxprocs=gomx, run_seconds=run_s)
                        if r:
                            flat_results[cell_key][backend_name].append(r)
                print(flush=True)

    # Aggregate after collection
    flat_results = {k: {b: aggregate(runs) for b, runs in backends.items()} for k, backends in flat_results.items()}

    print('[bench] === SUMMARY ===', flush=True)
    for cell_key, backends in sorted(flat_results.items(), key=_sort_cell_key):
        print(f'  {_cell_label(cell_key)}:', flush=True)
        for backend_name, agg in backends.items():
            if agg['n'] == 0:
                print(f'    {backend_name}: no data', flush=True)
            else:
                print(
                    f'    {backend_name}: fps/actor={agg["fps_per_actor_mean"]:.2f} ± {agg["fps_per_actor_std"]:.2f} '
                    f'(CV {agg["fps_per_actor_cv_pct"]:.0f}%, n={agg["n"]})',
                    flush=True,
                )
        go_agg = backends.get('go', {})
        py_agg = backends.get('python_mp', {})
        if go_agg.get('n', 0) > 0 and py_agg.get('n', 0) > 0 and py_agg['fps_per_actor_mean'] > 0:
            ratio = go_agg['fps_per_actor_mean'] / py_agg['fps_per_actor_mean']
            print(f'    ratio Go/Py = {ratio:.2f}x', flush=True)
    print(flush=True)

    _markdown_table(flat_results, out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
