"""Scan raw action JSON and group cost icons by MD5 hash.

The current command reads the historical external raw-data checkout at
``~/Documents/gicg_sim/data/raw/action`` and writes ``data/cost_icons/``.

输出:
- data/cost_icons/<md5>.png — 每个唯一 hash 的代表图
- data/cost_icons/_mapping.yaml — hash → [{id, name, sub_class, tags, cost}, ...] 映射

相同 hash 表示 URL 所标识的图像内容分组相同，可按组人工判定。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

URL_RE = re.compile(r'"costBgIcon"\s*:\s*\{[^}]*?"list"\s*:\s*\[\s*"(https://[^"]+)"', re.DOTALL)
HASH_RE = re.compile(r'/([0-9a-f]{32})_\d+\.png$')


def extract_url(raw_path: Path) -> str:
    text = raw_path.read_text(encoding='utf-8')
    m = URL_RE.search(text)
    if m:
        return m.group(1)
    text2 = text.replace('\\"', '"')
    m = URL_RE.search(text2)
    return m.group(1) if m else ''


def url_hash(url: str) -> str:
    m = HASH_RE.search(url)
    return m.group(1) if m else ''


def load_yaml(p: Path) -> dict:
    with open(p, encoding='utf-8') as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return {}


def main() -> int:
    raw_root = Path.home() / 'Documents/gicg_sim/data/raw/action'
    full_root = Path('data/full/action')
    out_dir = Path('data/cost_icons')
    out_dir.mkdir(parents=True, exist_ok=True)

    # hash → list of card meta + first url seen
    groups: dict[str, dict] = {}

    for raw in sorted(raw_root.glob('*.json')):
        if raw.name == '_index.json':
            continue
        url = extract_url(raw)
        h = url_hash(url)
        if not h:
            continue

        cid = raw.stem.split('_', 1)[0]
        # try matching full yaml for cost / sub_class / tags
        ypath = next(full_root.glob(f'{cid}_*.yaml'), None)
        meta = {'id': cid, 'name': raw.stem.split('_', 1)[1] if '_' in raw.stem else raw.stem}
        if ypath is not None:
            card = load_yaml(ypath)
            meta['sub_class'] = card.get('sub_class', '')
            meta['tags'] = card.get('tags', [])
            cost = card.get('cost', {})
            meta['cost'] = json.dumps(cost, ensure_ascii=False) if isinstance(cost, dict) else str(cost)
            cu = card.get('cost_unsure', '')
            if cu:
                meta['cost_unsure'] = True
        else:
            meta['cleansed'] = False

        g = groups.setdefault(h, {'url': url, 'cards': []})
        g['cards'].append(meta)

    # download each unique hash
    print(f'# {len(groups)} unique cost icon hashes', file=sys.stderr)
    n_dl = 0
    for h, g in groups.items():
        out = out_dir / f'{h}.png'
        if not out.exists():
            try:
                urllib.request.urlretrieve(g['url'], out)
                n_dl += 1
                print(f'  ↓ {h} ({len(g["cards"])} cards)', file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f'  ✗ {h}: {e}', file=sys.stderr)

    # write mapping yaml: hash → cards
    mapping = {h: g['cards'] for h, g in sorted(groups.items())}
    with open(out_dir / '_mapping.yaml', 'w', encoding='utf-8') as f:
        yaml.safe_dump(mapping, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # human-readable summary, sorted by group size desc
    lines: list[str] = []
    for h, g in sorted(groups.items(), key=lambda kv: -len(kv[1]['cards'])):
        cards = g['cards']
        lines.append(f'\n=== {h}  ({len(cards)} cards) ===')
        for c in cards:
            tags = ','.join(c.get('tags', []) or [])
            mark = ' [unsure]' if c.get('cost_unsure') else ''
            lines.append(
                f'  {c["id"]:>7} {c["name"]:<28} cost={c.get("cost", "?")}  sub={c.get("sub_class", "?")}  tags=[{tags}]{mark}'
            )
    summary_path = out_dir / '_summary.txt'
    summary_path.write_text('\n'.join(lines), encoding='utf-8')

    print(f'# downloaded {n_dl} new icons', file=sys.stderr)
    print(f'# mapping: {out_dir / "_mapping.yaml"}', file=sys.stderr)
    print(f'# summary: {summary_path}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
