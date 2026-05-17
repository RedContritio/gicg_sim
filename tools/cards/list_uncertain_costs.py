"""扫已 cleanse action yaml,列出 cost 不确定的卡 + costBgIcon URL。

不确定 = sub_class 是 事件牌/支援牌 且 cost N>0 且 cost 类型可能 same vs any。
武器/圣遗物/天赋/元素共鸣/0 cost 视为已确定,不列。

输出格式:
    <id> <name>  cost=<cost>  url=<costBgIcon>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ICON_RE = re.compile(r'"costBgIcon"\s*:\s*\{[^}]*?"list"\s*:\s*\[\s*"(https://[^"]+)"', re.DOTALL)


def extract_icon(raw_path: Path) -> str:
    text = raw_path.read_text(encoding='utf-8')
    m = ICON_RE.search(text)
    if m:
        return m.group(1)
    text2 = text.replace('\\"', '"')
    m = ICON_RE.search(text2)
    return m.group(1) if m else ''


def cost_is_certain(card: dict) -> bool:
    """返回 True = cost 已确定,不需 user review。"""
    tags = card.get('tags', []) or []
    sub = card.get('sub_class', '')
    cost = card.get('cost', {}) or {}
    if not isinstance(cost, dict):
        return True

    # 0 cost 简单
    n_total = sum(v for v in cost.values() if isinstance(v, int))
    if n_total == 0:
        return True

    # 武器/圣遗物 same:N 默认确定
    if any(t in tags for t in ('武器', '圣遗物', '天赋', '元素共鸣', '特技')):
        return True

    # specific 元素 cost(角色天赋 / 元素共鸣)— key 含中文元素名
    elem_keys = {'风', '火', '雷', '冰', '水', '草', '岩'}
    if any(k in elem_keys for k in cost.keys()):
        return True

    # 事件牌/支援牌(伙伴/场地/道具)+ N>0 → 不确定
    return False


def main() -> int:
    full_action = Path('data/full/action')
    raw_action = Path.home() / 'Documents/gicg_sim/data/raw/action'

    rows: list[tuple[int, str, str, str]] = []  # (id, name, cost_str, url)
    for yp in sorted(full_action.glob('*.yaml')):
        with open(yp, encoding='utf-8') as f:
            try:
                card = yaml.safe_load(f) or {}
            except yaml.YAMLError:
                continue
        if cost_is_certain(card):
            continue

        cid = card.get('id', '')
        name = card.get('name', yp.stem)
        cost = card.get('cost', {})
        cost_str = json.dumps(cost, ensure_ascii=False) if isinstance(cost, dict) else str(cost)

        # 找 raw,提取 cost_bg_icon
        url = card.get('cost_bg_icon_url', '')
        if not url:
            raws = list(raw_action.glob(f'{cid}_*.json'))
            if raws:
                url = extract_icon(raws[0])

        rows.append((int(cid) if str(cid).isdigit() else 0, name, cost_str, url))

    rows.sort()
    for cid, name, cost_str, url in rows:
        print(f'{cid} {name}  cost={cost_str}  {url}')
    print(f'\n# total uncertain: {len(rows)}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
