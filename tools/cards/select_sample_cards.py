#!/usr/bin/env python3
"""按 content_id 升序均匀 stride 选 sqrt(N) 张样本。

每个 type 独立取样:character / action / monster。stride = ceil(N / k),
k = ceil(sqrt(N))。打印每类的样本路径,供 cleansing 子任务处理。

默认读取历史外部 checkout ``~/Documents/gicg_sim/data/raw``。

用法::

    .venv/bin/python -m tools.cards.select_sample_cards
    .venv/bin/python -m tools.cards.select_sample_cards --raw-dir ~/Documents/gicg_sim/data/raw
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

DEFAULT_RAW = '~/Documents/gicg_sim/data/raw'
ID_RE = re.compile(r'^(\d+)_')


def collect_sorted(type_dir: Path) -> list[Path]:
    """返回按 content_id(filename 起首数字)升序的 .json 路径列表,
    跳过 _index.json。"""
    out: list[tuple[int, Path]] = []
    for p in type_dir.glob('*.json'):
        if p.name == '_index.json':
            continue
        m = ID_RE.match(p.name)
        if not m:
            continue
        out.append((int(m.group(1)), p))
    out.sort(key=lambda x: x[0])
    return [p for _, p in out]


def stride_pick(items: list[Path], k: int) -> list[Path]:
    """从 items 等距 stride 取 k 个(覆盖整段 ID 范围)。"""
    n = len(items)
    if n == 0 or k <= 0:
        return []
    if k >= n:
        return list(items)
    # 用 floor((i + 0.5) * n / k) 把 k 个采样点对齐到 cell 中点。
    return [items[int((i + 0.5) * n / k)] for i in range(k)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', default=DEFAULT_RAW, help='raw 根目录')
    ap.add_argument('--types', nargs='+', default=['character', 'action', 'monster'])
    args = ap.parse_args()

    root = Path(args.raw_dir).expanduser()
    if not root.is_dir():
        print(f'raw root 不存在: {root}', file=sys.stderr)
        return 1

    total = 0
    for t in args.types:
        type_dir = root / t
        if not type_dir.is_dir():
            print(f'  [skip] {type_dir} 不存在')
            continue
        items = collect_sorted(type_dir)
        n = len(items)
        k = math.ceil(math.sqrt(n))
        picked = stride_pick(items, k)
        print(f'\n=== {t} (N={n}, k=√N≈{k}, stride≈{n // k}) ===')
        for p in picked:
            print(p)
        total += len(picked)

    print(f'\nTOTAL {total} files', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
