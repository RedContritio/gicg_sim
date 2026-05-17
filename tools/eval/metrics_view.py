"""Quick view of artifacts/<run>/metrics.jsonl — last eval per baseline,
fps window(early vs late),loss/grad_norm trend + NaN/inf flag,episode count.

Usage::

    .venv/bin/python -m tools.eval.metrics_view artifacts/<run>/
    .venv/bin/python -m tools.eval.metrics_view artifacts/<run>/ --tail 20
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('run_dir', type=str)
    p.add_argument('--tail', type=int, default=10, help='train_step rows to print')
    args = p.parse_args()

    run = Path(args.run_dir)
    metrics = run / 'metrics.jsonl'
    if not metrics.exists():
        print(f'[metrics_view] not found: {metrics}', file=sys.stderr)
        return 1

    eps: list[dict] = []
    trains: list[dict] = []
    evals: list[dict] = []
    summary: dict | None = None
    for ln in metrics.read_text().splitlines():
        try:
            d = json.loads(ln)
        except Exception:
            continue
        k = d.get('kind')
        if k == 'episode':
            eps.append(d)
        elif k == 'train_step':
            trains.append(d)
        elif k == 'eval':
            evals.append(d)
        elif k == 'final':
            summary = d

    print(f'== {run.name} ==')
    if eps:
        ep0, epN = eps[0], eps[-1]
        df = epN.get('frames', 0) - ep0.get('frames', 0)
        dt = epN.get('wall_s', 0) - ep0.get('wall_s', 0)
        fps = df / dt if dt > 0 else float('nan')
        print(f'episodes: {len(eps)}, last frames={epN.get("frames")}, fps={fps:.2f}')
        n_half = len(eps) // 2 or 1
        if n_half >= 5:
            early, late = eps[:n_half], eps[n_half:]
            de_w = early[-1]['wall_s'] - early[0]['wall_s']
            dl_w = late[-1]['wall_s'] - late[0]['wall_s']
            fps_e = (early[-1]['frames'] - early[0]['frames']) / de_w if de_w > 0 else float('nan')
            fps_l = (late[-1]['frames'] - late[0]['frames']) / dl_w if dl_w > 0 else float('nan')
            print(f'  fps early/late: {fps_e:.2f} / {fps_l:.2f}')

    if trains:
        last = trains[-args.tail :]
        if any(not math.isfinite(t.get('loss', 0)) for t in trains):
            print(f'⚠ train: NaN/inf loss detected in {len(trains)} steps')
        print(f'train_steps (last {len(last)}):')
        for t in last:
            print(f'  step={t.get("step")} frames={t.get("frames")} loss={t.get("loss"):.4f}')

    if evals:
        last_e = evals[-1]
        print(f'last eval @ frames={last_e.get("frames")}:')
        for k, v in last_e.items():
            if isinstance(v, dict) and 'wp_mean' in v:
                w = v.get('ci95_hi', 0) - v.get('ci95_lo', 0)
                print(f'  {k}: wp={v["wp_mean"]:.3f} ci95±{w / 2:.3f}')

    if summary:
        print(f'FINAL: frames={summary.get("frames")} wall_s={summary.get("wall_s")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
