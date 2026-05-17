#!/usr/bin/env python3
"""列出 raw - cleaned 差集,按 batch 切分供 sonnet subagent 处理。

每张 raw 检查 ``data/cleaned/<type>/<stem>.yaml`` 是否存在;不存在 = pending。
按 ``--batch-size`` 切分输出,每个 batch 印一行 ``;``-join 的路径(便于
subagent prompt 拼接)。

用法(repo root)::

    .venv/bin/python -m tools.list_pending_cards
    .venv/bin/python -m tools.list_pending_cards --batch-size 4 --types character
    .venv/bin/python -m tools.list_pending_cards --batch 17        # 只印第 17 个 batch
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_RAW = '~/Documents/gicg_sim/data/raw'
DEFAULT_CLEANED = 'data/cleaned'
ID_RE = re.compile(r'^(\d+)_')


def collect_pending(raw_dir: Path, cleaned_dir: Path, types: list[str]) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for t in types:
        type_dir = raw_dir / t
        if not type_dir.is_dir():
            continue
        cleaned_stems = {p.stem for p in (cleaned_dir / t).glob('*.yaml')}
        pending: list[tuple[int, Path]] = []
        for p in type_dir.glob('*.json'):
            if p.name == '_index.json':
                continue
            if p.stem in cleaned_stems:
                continue
            m = ID_RE.match(p.name)
            content_id = int(m.group(1)) if m else 0
            pending.append((content_id, p))
        pending.sort(key=lambda x: x[0])
        out[t] = [p for _, p in pending]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', default=DEFAULT_RAW)
    ap.add_argument('--cleaned-dir', default=DEFAULT_CLEANED)
    ap.add_argument('--types', nargs='+', default=['character', 'action', 'monster'])
    ap.add_argument('--batch-size', type=int, default=4, help='每个 batch 卡数')
    ap.add_argument('--batch', type=int, default=None, help='只印第 N 个 batch (1-indexed)')
    ap.add_argument('--paths-only', action='store_true', help='只印路径(每行 1 个),不印 batch header')
    args = ap.parse_args()

    raw_root = Path(args.raw_dir).expanduser()
    cleaned_root = Path(args.cleaned_dir)
    if not raw_root.is_dir():
        print(f'raw root 不存在: {raw_root}', file=sys.stderr)
        return 1

    pending = collect_pending(raw_root, cleaned_root, args.types)
    total = sum(len(ps) for ps in pending.values())
    if not args.paths_only:
        print(f'# raw_dir={raw_root}  cleaned_dir={cleaned_root}', file=sys.stderr)
        for t, ps in pending.items():
            print(f'# {t}: pending={len(ps)}', file=sys.stderr)
        print(f'# TOTAL pending={total}, batch_size={args.batch_size}', file=sys.stderr)

    flat: list[Path] = []
    for t in args.types:
        flat.extend(pending.get(t, []))

    n_batches = (len(flat) + args.batch_size - 1) // args.batch_size
    if not args.paths_only:
        print(f'# n_batches={n_batches}', file=sys.stderr)

    if args.paths_only:
        for p in flat:
            print(p)
        return 0

    for i in range(n_batches):
        if args.batch is not None and i + 1 != args.batch:
            continue
        chunk = flat[i * args.batch_size : (i + 1) * args.batch_size]
        print(f'--- batch {i + 1}/{n_batches} ({len(chunk)}) ---')
        for p in chunk:
            print(p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
