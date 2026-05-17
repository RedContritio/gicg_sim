"""检查 entry_page raw (data/raw/<type>/) 与 list ext (data/raw_list/<type>.json) 是否同步。

list 数据是批量拉取(per channel),entry_page 是单卡拉(per content_id);
两者 wiki 更新可能不同步,parser 严格要求两者 content_id 集合一致。

用法(从 repo root)::

    .venv/bin/python -m tools.cards.check_list_sync
    .venv/bin/python -m tools.cards.check_list_sync --raw-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CHANNELS = ('character', 'action', 'monster')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', default='/Users/redcontritio/Documents/gicg_sim/data/raw')
    ap.add_argument('--list-dir', default='data/raw_list')
    args = ap.parse_args()

    raw_root = Path(args.raw_dir)
    list_root = Path(args.list_dir)

    overall_ok = True
    for kind in CHANNELS:
        raw_dir = raw_root / kind
        list_fp = list_root / f'{kind}.json'
        if not raw_dir.is_dir():
            print(f'[skip] {kind}:raw 目录不存在 {raw_dir}', file=sys.stderr)
            continue
        if not list_fp.exists():
            print(f'[error] {kind}:list 文件不存在 {list_fp}', file=sys.stderr)
            overall_ok = False
            continue

        # entry_page raw:从文件名 <id>_<name>.json 提 id
        raw_ids: set[int] = set()
        for fp in raw_dir.glob('*.json'):
            if fp.name == '_index.json':
                continue
            m = re.match(r'^(\d+)_', fp.name)
            if m:
                raw_ids.add(int(m.group(1)))

        # list ext:从 json content_id 提
        list_items = json.loads(list_fp.read_text(encoding='utf-8'))
        list_ids: set[int] = {it['content_id'] for it in list_items if 'content_id' in it}

        only_raw = raw_ids - list_ids
        only_list = list_ids - raw_ids
        common = raw_ids & list_ids
        print(f'\n## {kind} (channel)')
        print(f'  raw entry_page: {len(raw_ids)} 张')
        print(f'  list ext:       {len(list_ids)} 张')
        print(f'  共有:           {len(common)} 张')
        if only_raw:
            print(
                f'  ⚠ 仅 raw 有(list 缺,需重 fetch_list 或卡已下架):{sorted(only_raw)[:10]}'
                + (f' ...(+{len(only_raw) - 10})' if len(only_raw) > 10 else '')
            )
            overall_ok = False
        if only_list:
            print(
                f'  ⚠ 仅 list 有(raw 缺,需 fetch entry_page):{sorted(only_list)[:10]}'
                + (f' ...(+{len(only_list) - 10})' if len(only_list) > 10 else '')
            )
            overall_ok = False
        if not only_raw and not only_list:
            print(f'  ✓ 同步')

    if not overall_ok:
        print('\n建议:', file=sys.stderr)
        print('  - 仅 list 有 → 跑 .venv/bin/python -m tools.cards.fetch --type <kind>', file=sys.stderr)
        print('  - 仅 raw 有 → 跑 .venv/bin/python -m tools.cards.fetch_list --type <kind>', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
