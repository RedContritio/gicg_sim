"""Parse Win bench metrics.jsonl pair (Python mp vs Go-actor) and dump comparison。

Usage:
    .venv/bin/python -m tools._bench.parse_win_bench \\
        --py-mp artifacts/.../metrics.jsonl \\
        --go    artifacts/.../metrics.jsonl \\
        --out   tools/_bench/win_results.md

Reads both metrics.jsonl, computes steady-state (skip first 10% frames) fps / mem /
batching_efficiency / sub-span timings,dumps markdown table。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


def _load_metrics(path: Path) -> dict:
    if not path.exists():
        return {'error': f'not found: {path}'}
    iters = []
    mem_rss = []
    inf = []
    qs = []
    alive = []
    go_perf: dict[str, dict] = defaultdict(lambda: {'n': 0, 'sum_ms': 0.0, 'max_ms': 0.0})
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            k = r['kind']
            if k == 'iter':
                iters.append(r)
            elif k == 'mem':
                mem_rss.append(r.get('master_rss_mb', 0))
            elif k == 'inf_server':
                inf.append(r)
            elif k == 'trans_queue':
                qs.append(r['qsize'])
            elif k == 'go_alive_count':
                alive.append(r['count'])
            elif k == 'go_perf':
                for n, st in r.get('stages', {}).items():
                    go_perf[n]['n'] += st['n']
                    go_perf[n]['sum_ms'] += st['sum_ms']
                    if st['max_ms'] > go_perf[n]['max_ms']:
                        go_perf[n]['max_ms'] = st['max_ms']
    if not iters:
        return {'error': 'no iter rows'}
    skip = max(1, len(iters) // 10)
    ss = iters[skip:]
    fps = (ss[-1]['frames'] - ss[0]['frames']) / (ss[-1]['wall_s'] - ss[0]['wall_s']) if len(ss) > 1 else 0
    eps = (ss[-1]['episodes'] - ss[0]['episodes']) / (ss[-1]['wall_s'] - ss[0]['wall_s']) if len(ss) > 1 else 0
    inf_be = [r['batching_efficiency'] for r in inf if 'batching_efficiency' in r]
    inf_bs = [r['batch_size_avg'] for r in inf if 'batch_size_avg' in r]
    inf_fwms = [r['forward_ms_avg'] for r in inf if 'forward_ms_avg' in r]
    return {
        'art_dir': str(path.parent.name),
        'frames_total': iters[-1]['frames'],
        'wall_s': iters[-1]['wall_s'],
        'fps_steady': round(fps, 2),
        'eps_per_s': round(eps, 3),
        'mem_rss_mb_max': round(max(mem_rss), 0) if mem_rss else 0,
        'mem_rss_mb_final': round(mem_rss[-1], 0) if mem_rss else 0,
        'batching_efficiency_mean': round(sum(inf_be) / len(inf_be), 3) if inf_be else None,
        'batch_size_avg_mean': round(sum(inf_bs) / len(inf_bs), 2) if inf_bs else None,
        'forward_ms_avg_mean': round(sum(inf_fwms) / len(inf_fwms), 2) if inf_fwms else None,
        'qs_max': max(qs) if qs else None,
        'qs_mean': round(sum(qs) / len(qs), 1) if qs else None,
        'alive_unique': sorted(set(alive)) if alive else None,
        'go_perf': {k: {**v, 'mean_ms': round(v['sum_ms'] / v['n'], 3) if v['n'] else 0} for k, v in go_perf.items()},
    }


def _md_table(py: dict, go: dict) -> str:
    md = '# I29 T-C2 Win N=16 fair bench results\n\n'
    md += f'Date: $(date)\n\nPython mp dir: `{py.get("art_dir", "?")}`\nGo-actor dir: `{go.get("art_dir", "?")}`\n\n'
    md += '## Headline\n\n'
    md += '| Metric | Python mp | Go-actor | Ratio (Go/Py) |\n'
    md += '|--------|----------:|---------:|--------------:|\n'

    def _ratio(a, b):
        if a and b:
            return f'{a / b:.2f}x'
        return '-'

    def _safe(x):
        return x if x is not None else '-'

    py_fps = py.get('fps_steady', 0)
    go_fps = go.get('fps_steady', 0)
    md += f'| fps (steady) | {py_fps} | {go_fps} | {_ratio(go_fps, py_fps)} |\n'
    md += f'| eps/s | {_safe(py.get("eps_per_s"))} | {_safe(go.get("eps_per_s"))} | {_ratio(go.get("eps_per_s"), py.get("eps_per_s"))} |\n'
    md += f'| master_rss_mb max | {_safe(py.get("mem_rss_mb_max"))} | {_safe(go.get("mem_rss_mb_max"))} | {_ratio(go.get("mem_rss_mb_max"), py.get("mem_rss_mb_max"))} |\n'
    md += f'| batching_efficiency mean | {_safe(py.get("batching_efficiency_mean"))} | {_safe(go.get("batching_efficiency_mean"))} | - |\n'
    md += f'| batch_size_avg mean | {_safe(py.get("batch_size_avg_mean"))} | {_safe(go.get("batch_size_avg_mean"))} | - |\n'
    md += f'| forward_ms_avg mean | {_safe(py.get("forward_ms_avg_mean"))} | {_safe(go.get("forward_ms_avg_mean"))} | - |\n'

    if go.get('go_perf'):
        md += '\n## Go-actor sub-span timing (Go-actor only)\n\n'
        md += '| Stage | n calls | mean_ms | max_ms |\n|---|--:|--:|--:|\n'
        for name in sorted(go['go_perf']):
            st = go['go_perf'][name]
            if st['n'] == 0:
                continue
            md += f'| `{name}` | {st["n"]} | {st["mean_ms"]:.3f} | {st["max_ms"]:.3f} |\n'
        md += '\n注:观察 transition_writer.mutex_wait 是否 ≈ 0 (T-B1 fix 验证)。\n'
        md += '观察 inference_client.recv 大小 - send 时间差 ≈ InfServer batching window + GPU forward。\n'

    if go.get('qs_max') is not None:
        md += f'\n## Go-actor backpressure\n\n- _trans_queue.qsize max = {go["qs_max"]} / mean = {go["qs_mean"]}\n'
        md += f'- alive_count unique = {go["alive_unique"]}\n'

    return md


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--py-mp', type=str, required=True)
    ap.add_argument('--go', type=str, required=True)
    ap.add_argument('--out', type=str, required=True)
    args = ap.parse_args()
    py = _load_metrics(Path(args.py_mp))
    go = _load_metrics(Path(args.go))
    md = _md_table(py, go)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding='utf-8')
    print(md)
    print(f'\n[parse] dumped {out}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
