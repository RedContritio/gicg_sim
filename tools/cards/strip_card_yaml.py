#!/usr/bin/env python3
"""data/full/<type>/<id>.yaml → data/cleaned/<type>/<id>.yaml — 删除纯 visual / audit 字段。

Sonnet subagent 输出的 full YAML 含所有原始数据(URL/icon/HTML/version)
+ 推断字段。本工具递归删除 ``_DROP_KEYS`` 列出的字段,只留分析需要的
机制信息。LLM gap 分析就读 cleaned/。

用法(从 repo root)::

    .venv/bin/python -m tools.strip_card_yaml --in data/full --out data/cleaned
    .venv/bin/python -m tools.strip_card_yaml --in data/full --out data/cleaned --merge-glossary

``--merge-glossary`` 额外产出 ``data/cleaned/_glossary.yaml`` — 全卡 terms
合并(同名取最长解释,记 ``_seen_in: [card_id, ...]``)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Drop these keys recursively wherever they appear in the YAML tree.
# 只删纯 visual / audit / 双份(已被 *_text 取代)字段。所有机制字段都保留。
_DROP_KEYS = frozenset(
    {
        'icon_url',
        'header_img_url',
        'icon',  # skill[].icon, talent.icon
        'version',
        'desc',  # raw 顶层 desc 通常重复 name,且无机制信息
        'effect_html',
        'desc_html',
        'flavor_html',
        '_raw_path',
        # raw_value/raw_life/raw_energy 保留(audit 用)— 不删。
    }
)


def strip_dict(obj):
    """Recursively delete _DROP_KEYS from any dict in the tree. Returns
    a new structure (input unchanged), preserves list / scalar nodes."""
    if isinstance(obj, dict):
        return {k: strip_dict(v) for k, v in obj.items() if k not in _DROP_KEYS}
    if isinstance(obj, list):
        return [strip_dict(item) for item in obj]
    return obj


def load_yaml(path: Path) -> dict:
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def dump_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def merge_glossary(cleaned_dir: Path, out_path: Path) -> int:
    """Walk every cleaned YAML, fold its ``terms`` into a single global
    glossary. Conflict resolution: longest explanation wins; track
    ``_seen_in`` (sorted list of card ids that referenced the term).
    Returns the number of unique terms collected."""
    glossary: dict[str, dict] = {}
    for yaml_path in cleaned_dir.rglob('*.yaml'):
        if yaml_path.name == '_glossary.yaml':
            continue
        try:
            data = load_yaml(yaml_path)
        except yaml.YAMLError as e:
            print(f'  [skip] {yaml_path}: {e}', file=sys.stderr)
            continue
        card_id = str(data.get('id', yaml_path.stem))
        terms = data.get('terms', {}) or {}
        if not isinstance(terms, dict):
            continue
        for name, explanation in terms.items():
            entry = glossary.setdefault(name, {'text': '', '_seen_in': []})
            text = explanation if isinstance(explanation, str) else str(explanation)
            if len(text) > len(entry['text']):
                entry['text'] = text
            if card_id not in entry['_seen_in']:
                entry['_seen_in'].append(card_id)
    for entry in glossary.values():
        entry['_seen_in'].sort()
    out: dict[str, dict] = {k: glossary[k] for k in sorted(glossary.keys())}
    dump_yaml(out, out_path)
    return len(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='in_dir', default='data/full', help='full YAML 根目录')
    ap.add_argument('--out', dest='out_dir', default='data/cleaned', help='cleaned 输出根目录')
    ap.add_argument('--merge-glossary', action='store_true', help='额外产出 cleaned/_glossary.yaml')
    args = ap.parse_args()

    in_root = Path(args.in_dir)
    out_root = Path(args.out_dir)
    if not in_root.is_dir():
        print(f'输入目录不存在: {in_root}', file=sys.stderr)
        return 1

    yaml_files = list(in_root.rglob('*.yaml'))
    n_ok = 0
    for src in yaml_files:
        rel = src.relative_to(in_root)
        dst = out_root / rel
        try:
            data = load_yaml(src)
        except yaml.YAMLError as e:
            print(f'✗ {rel}: {e}', file=sys.stderr)
            continue
        stripped = strip_dict(data)
        dump_yaml(stripped, dst)
        n_ok += 1
        print(f'[{n_ok}/{len(yaml_files)}] ✓ {rel}')

    if args.merge_glossary:
        glossary_path = out_root / '_glossary.yaml'
        n_terms = merge_glossary(out_root, glossary_path)
        print(f'\nglossary: {n_terms} 个术语 → {glossary_path}')

    print(f'\n完成 {n_ok}/{len(yaml_files)}')
    return 0 if n_ok == len(yaml_files) else 1


if __name__ == '__main__':
    sys.exit(main())
