"""Compare multiple eval JSON outputs (from tools.eval.ckpt) as markdown
table. Useful for ablation runs / staged ckpt comparisons.

Usage::

    .venv/bin/python -m tools.eval.compare /tmp/cmp/summary.json
    .venv/bin/python -m tools.eval.compare a.json b.json c.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('jsons', nargs='+', type=str)
    args = p.parse_args()

    rows: dict[str, dict[str, float]] = {}
    cis: dict[str, dict[str, float]] = {}
    all_baselines: set[str] = set()
    for j in args.jsons:
        blob = json.loads(Path(j).read_text())
        # Either tools.eval.ckpt summary form {'ckpts': {label: {'baselines': {...}}}}
        # or legacy single-ckpt form {'ckpt': ..., 'baselines': {...}}
        ckpts_dict = blob.get('ckpts') or {Path(j).stem: {'baselines': blob.get('baselines', {})}}
        for label, payload in ckpts_dict.items():
            rows.setdefault(label, {})
            cis.setdefault(label, {})
            for bn, m in payload.get('baselines', {}).items():
                rows[label][bn] = m['wp_mean']
                cis[label][bn] = (m['ci95_hi'] - m['ci95_lo']) / 2
                all_baselines.add(bn)

    bls = sorted(all_baselines)
    print('| ckpt | ' + ' | '.join(bls) + ' |')
    print('|---|' + '|'.join(['---'] * len(bls)) + '|')
    for label in sorted(rows):
        cells = []
        for bn in bls:
            if bn in rows[label]:
                cells.append(f'{rows[label][bn]:.3f} ±{cis[label][bn]:.3f}')
            else:
                cells.append('—')
        print(f'| {label} | ' + ' | '.join(cells) + ' |')
    return 0


if __name__ == '__main__':
    sys.exit(main())
