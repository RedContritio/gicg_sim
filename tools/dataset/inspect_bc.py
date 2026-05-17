"""Inspect a BC dataset.npz — shapes, label distribution, z balance."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('dataset', type=str, help='Path to dataset.npz')
    args = ap.parse_args()

    d = np.load(args.dataset)
    print(f'file: {args.dataset}')
    for k in d.files:
        arr = d[k]
        print(f'  {k}: shape={arr.shape} dtype={arr.dtype}')

    action = d['action']
    mask = d['legal_mask']
    z = d['terminal_z']

    n = len(action)
    print(f'\nn_decisions: {n}')
    print(
        f'legal-count per decision: mean={mask.sum(axis=1).mean():.2f} median={np.median(mask.sum(axis=1)):.1f} max={mask.sum(axis=1).max()}'
    )
    print(f'action index distribution (top 10): ')
    vals, cnts = np.unique(action, return_counts=True)
    order = np.argsort(cnts)[::-1][:10]
    for i in order:
        print(f'  idx={vals[i]:>3d}  count={cnts[i]:>5d}  ({cnts[i] / n:.1%})')

    print(f'\nterminal_z distribution:')
    for zv, label in [(1.0, 'win'), (-1.0, 'loss'), (0.0, 'draw')]:
        c = int((z == zv).sum())
        print(f'  z={zv:+.0f} ({label:>4s}): {c:>6d} ({c / n:.1%})')

    # Tied-set stats — BC ceiling = 1 / mean_tied.
    if 'tied_mask' in d.files:
        tm = d['tied_mask']
        tsize = tm.sum(axis=1)
        print(
            f'\ntied_set_size: mean={tsize.mean():.2f}  median={np.median(tsize):.1f}  p90={np.percentile(tsize, 90):.0f}  max={tsize.max()}'
        )
        print(f'  fraction tied==1: {(tsize == 1).mean():.3f}')
        print(f'  BC match-rate ceiling (hard argmax): {1 / tsize.mean():.3f}')
        # Sanity: teacher action ∈ tied set
        action_in_tied = sum(1 for i in range(n) if tm[i, action[i]])
        print(f'  sanity: teacher action ∈ tied set: {action_in_tied}/{n}')

    # Sanity: is teacher action always a legal action?
    bad = 0
    for i in range(min(n, 1000)):  # sample
        if not mask[i, action[i]]:
            bad += 1
    print(f'\nsanity check (first min(n,1000) decisions): illegal action count = {bad}')


if __name__ == '__main__':
    main()
