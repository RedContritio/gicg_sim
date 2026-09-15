"""I29 T-C1 Mac fair bench harness — run Python mp + Go-actor pair with N seeds,
then aggregate and dump comparison markdown。

Usage:
    .venv/bin/python -m tools._bench.run_mac_pair \\
        --num-actors 4 \\
        --seeds 1 2 3 \\
        --total-frames 30000 \\
        --out tools/_bench/results_mac_n4.md

会顺序跑(避 parallel 互扰 Mac CPU):
    seed=1: python_mp / go_actor
    seed=2: python_mp / go_actor
    seed=3: python_mp / go_actor

每 run 通过 tools.runs.train 起子进程 + override num_actors + seed + total_frames。
完成后扫 artifacts/<NNN>_bench_v_legacy_mac_*/metrics.jsonl 计算:
- fps mean ± std (steady-state, skip first 10% frames warm-up)
- master_rss_mb mean ± std
- iter_rate trans_rate (frames/iter * iter/s = fps)
- 各 Go perf sub-span mean_ms / call_n / wall_pct
- 各 Python perf assembler.* sub-span mean_ms
- trans_queue.qsize percentile (p50, p95)
- go_alive_count consistency (should == num_actors)
- decode_errors (should == 0)
- 对比表 markdown
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_one(cfg: str, num_actors: int, seed: int, total_frames: int) -> Optional[Path]:
    """Run one cfg via tools.runs.train,返 artifacts dir。"""
    cmd = [
        '.venv/bin/python',
        '-m',
        'tools.runs.train',
        f'configs/dmc/{cfg}.toml',
        '--override',
        f'pipeline.num_actors={num_actors}',
        '--override',
        f'meta.seed={seed}',
        '--override',
        f'paradigm.dmc.total_frames={total_frames}',
    ]
    print(f'[bench] starting {cfg} N={num_actors} seed={seed} frames={total_frames}', flush=True)
    t0 = time.monotonic()
    r = subprocess.run(cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=3600)
    dt = time.monotonic() - t0
    if r.returncode != 0:
        print(f'[bench] FAIL rc={r.returncode} stderr tail:', flush=True)
        print(r.stderr[-2000:], flush=True)
        return None
    # tools.runs.train 输出 artifact dir 路径(看 stdout)
    out = r.stdout
    art_dir = None
    for line in out.splitlines():
        if 'artifacts/' in line and ('_bench_v_legacy_mac' in line):
            for tok in line.split():
                if 'artifacts/' in tok and '_bench_v_legacy_mac' in tok:
                    art_dir = Path(tok.strip().rstrip('/.,;'))
                    break
            if art_dir:
                break
    if art_dir is None or not art_dir.exists():
        # 回退:扫最新的 artifacts dir
        cand = sorted(
            (_REPO_ROOT / 'artifacts').glob('*_bench_v_legacy_mac_*'),
            key=lambda p: p.stat().st_mtime,
        )
        if cand:
            art_dir = cand[-1]
    print(f'[bench] done {cfg} N={num_actors} seed={seed} wall={dt:.1f}s dir={art_dir}', flush=True)
    return art_dir


def _parse_metrics(art_dir: Path, warm_skip_frac: float = 0.1) -> dict:
    """Parse metrics.jsonl + Python perf jsonl,返 aggregated stats。"""
    metrics = art_dir / 'metrics.jsonl'
    if not metrics.exists():
        return {'error': f'no metrics.jsonl in {art_dir}'}

    iters = []
    mem_rss = []
    go_perf_stages: dict[str, dict] = defaultdict(lambda: {'n': 0, 'sum_ms': 0.0, 'max_ms': 0.0})
    qsizes = []
    alive = []
    with open(metrics) as f:
        for line in f:
            r = json.loads(line)
            k = r['kind']
            if k == 'iter':
                iters.append(r)
            elif k == 'mem':
                mem_rss.append(r.get('master_rss_mb', 0))
            elif k == 'go_perf':
                for name, st in r.get('stages', {}).items():
                    go_perf_stages[name]['n'] += st['n']
                    go_perf_stages[name]['sum_ms'] += st['sum_ms']
                    if st['max_ms'] > go_perf_stages[name]['max_ms']:
                        go_perf_stages[name]['max_ms'] = st['max_ms']
            elif k == 'trans_queue':
                qsizes.append(r['qsize'])
            elif k == 'go_alive_count':
                alive.append(r['count'])

    if not iters:
        return {'error': 'no iter rows'}

    # steady-state: skip first warm_skip_frac
    skip_n = max(1, int(len(iters) * warm_skip_frac))
    iters_ss = iters[skip_n:]

    total_frames = iters_ss[-1]['frames'] - iters_ss[0]['frames']
    total_wall = iters_ss[-1]['wall_s'] - iters_ss[0]['wall_s']
    fps = total_frames / total_wall if total_wall > 0 else 0
    eps = (iters_ss[-1]['episodes'] - iters_ss[0]['episodes']) / total_wall

    # Python perf jsonl (assembler.* spans)
    py_stages: dict[str, dict] = defaultdict(lambda: {'n': 0, 'sum_ms': 0.0})
    py_dir = art_dir / '_perf'
    if py_dir.exists():
        for pf in py_dir.glob('*.jsonl'):
            with open(pf) as f:
                for line in f:
                    r = json.loads(line)
                    for name, st in r.get('stages', {}).items():
                        py_stages[name]['n'] += st['n']
                        py_stages[name]['sum_ms'] += st.get('mean_ms', 0) * st['n']

    return {
        'art_dir': str(art_dir.name),
        'n_iters': len(iters),
        'wall_s_ss': round(total_wall, 1),
        'fps': round(fps, 2),
        'eps_per_s': round(eps, 3),
        'mem_rss_mb_max': round(max(mem_rss), 0) if mem_rss else 0,
        'mem_rss_mb_final': round(mem_rss[-1], 0) if mem_rss else 0,
        'go_perf_stages': {k: dict(v) for k, v in go_perf_stages.items()},
        'py_stages': {k: dict(v) for k, v in py_stages.items()},
        'qsize_max': max(qsizes) if qsizes else None,
        'qsize_mean': round(sum(qsizes) / len(qsizes), 1) if qsizes else None,
        'alive_count_unique': sorted(set(alive)) if alive else None,
    }


def _aggregate(runs: list[dict]) -> dict:
    """Aggregate over multiple seeds — mean ± std of key metrics。"""
    if not runs:
        return {}
    fps_vals = [r['fps'] for r in runs if 'fps' in r]
    mem_vals = [r['mem_rss_mb_max'] for r in runs if 'mem_rss_mb_max' in r]
    return {
        'n_runs': len(runs),
        'fps_mean': round(mean(fps_vals), 2) if fps_vals else 0,
        'fps_std': round(stdev(fps_vals), 2) if len(fps_vals) > 1 else 0,
        'mem_rss_mb_max_mean': round(mean(mem_vals), 0) if mem_vals else 0,
        'individual_runs': runs,
    }


def _markdown_dump(results: dict, num_actors: int, out_path: Path) -> None:
    py = results['python_mp']
    go = results['go']
    md = f"""# I29 T-C1 Mac fair bench results — N={num_actors}

Commit: {results['commit']}
Date: {results['date']}
Seeds: {results['seeds']}
Frames per run: {results['total_frames']}

## Headline

| Metric | Python mp | Go-actor | Ratio (Go/Py) |
|--------|-----------|----------|---------------|
| fps mean ± std | {py['fps_mean']:.2f} ± {py['fps_std']:.2f} | {go['fps_mean']:.2f} ± {go['fps_std']:.2f} | {go['fps_mean'] / py['fps_mean']:.2f}x |
| master_rss_mb max | {py['mem_rss_mb_max_mean']:.0f} | {go['mem_rss_mb_max_mean']:.0f} | {go['mem_rss_mb_max_mean'] / py['mem_rss_mb_max_mean']:.2f}x |
| N runs | {py['n_runs']} | {go['n_runs']} | - |

## Per-run detail

### Python mp
"""
    for r in py['individual_runs']:
        md += f'- seed=?: fps={r.get("fps")} mem_max={r.get("mem_rss_mb_max")}MB wall={r.get("wall_s_ss")}s dir={r.get("art_dir")}\n'
    md += '\n### Go-actor\n'
    for r in go['individual_runs']:
        md += f'- seed=?: fps={r.get("fps")} mem_max={r.get("mem_rss_mb_max")}MB wall={r.get("wall_s_ss")}s dir={r.get("art_dir")}\n'

    # Sub-span comparison (Go side perf trace)
    if go['individual_runs']:
        md += '\n## Go sub-span aggregate (Go-actor only,across seeds)\n\n'
        agg_stages: dict[str, dict] = defaultdict(lambda: {'n': 0, 'sum_ms': 0.0})
        for run in go['individual_runs']:
            for name, st in run.get('go_perf_stages', {}).items():
                agg_stages[name]['n'] += st['n']
                agg_stages[name]['sum_ms'] += st['sum_ms']
        md += f'| Stage | n calls | mean_ms |\n|-------|--------:|--------:|\n'
        for name in sorted(agg_stages):
            st = agg_stages[name]
            if st['n'] == 0:
                continue
            mean_ms = st['sum_ms'] / st['n']
            md += f'| `{name}` | {st["n"]} | {mean_ms:.3f} |\n'

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding='utf-8')
    print(f'[bench] dumped {out_path}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--num-actors', type=int, required=True)
    ap.add_argument('--seeds', type=int, nargs='+', default=[1, 2, 3])
    ap.add_argument('--total-frames', type=int, default=30000)
    ap.add_argument('--out', type=str, required=True)
    args = ap.parse_args()

    # Build c-shared libs first (skip if exist).
    if not (_REPO_ROOT / 'gicg_env' / 'libgicg_actor.dylib').exists():
        print('[bench] building c-shared libs...')
        subprocess.run(
            ['go', 'build', '-buildmode=c-shared', '-o', 'gicg_env/libgicg_actor.dylib', './gicg_actor/capi/'],
            cwd=str(_REPO_ROOT),
            check=True,
        )
        subprocess.run(
            ['go', 'build', '-buildmode=c-shared', '-o', 'gicg_env/libgicg.dylib', './gicg_engine/capi/'],
            cwd=str(_REPO_ROOT),
            check=True,
        )

    runs_py = []
    runs_go = []
    for seed in args.seeds:
        # Python mp
        art = _run_one('bench_v_legacy_mac_python_mp', args.num_actors, seed, args.total_frames)
        if art:
            runs_py.append({**_parse_metrics(art), 'seed': seed})
        # Go-actor
        art = _run_one('bench_v_legacy_mac_go', args.num_actors, seed, args.total_frames)
        if art:
            runs_go.append({**_parse_metrics(art), 'seed': seed})

    results = {
        'commit': subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(_REPO_ROOT), text=True
        ).strip(),
        'date': time.strftime('%Y-%m-%d %H:%M'),
        'seeds': args.seeds,
        'total_frames': args.total_frames,
        'python_mp': _aggregate(runs_py),
        'go': _aggregate(runs_go),
    }
    _markdown_dump(results, args.num_actors, Path(args.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
