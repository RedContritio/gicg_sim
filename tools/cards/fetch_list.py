"""批量拉取 mihoyo wiki content/list API,存 data/raw_list/<type>.json。

list API 跟单卡 entry_page(由 ``tools.cards.fetch`` 拉)是两个独立信源:
- entry_page = per-card 详情(modules / attr / desc HTML)
- list = per-channel 卡牌总目录,带 ext.costBgIcon / energyBgIcon / filter.text

两者的 cost 信号在 transform 阶段交叉验证。

用法(从 repo root)::

    .venv/bin/python -m tools.cards.fetch_list
    .venv/bin/python -m tools.cards.fetch_list --type action
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

URL = 'https://act-api-takumi-static.mihoyo.com/common/blackboard/ys_obc/v1/home/content/list'
HEADERS = {
    'accept': 'application/json',
    'origin': 'https://baike.mihoyo.com',
    'referer': 'https://baike.mihoyo.com/',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/147.0.0.0',
}
CHANNELS = {'character': 233, 'action': 234, 'monster': 235}


def fetch_list(channel_id: int, timeout: float = 30.0) -> list[dict]:
    req = urllib.request.Request(f'{URL}?app_sn=ys_obc&channel_id={channel_id}', headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode('utf-8'))
    if data.get('retcode') != 0:
        raise RuntimeError(f'list API error (channel={channel_id}): {data.get("message")}')
    items = data.get('data', {}).get('list') or []
    if not items:
        raise RuntimeError(f'list API empty (channel={channel_id})')
    return items[0].get('list') or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='data/raw_list')
    ap.add_argument('--type', choices=['character', 'action', 'monster', 'all'], default='all')
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    types = list(CHANNELS) if args.type == 'all' else [args.type]
    for t in types:
        ch = CHANNELS[t]
        inner = fetch_list(ch)
        tgt = out / f'{t}.json'
        tgt.write_text(json.dumps(inner, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{t}: {len(inner)} items → {tgt}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
