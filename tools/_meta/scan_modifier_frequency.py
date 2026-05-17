#!/usr/bin/env python3
"""ADR-0019 §B.0 — modifier 频次实证统计工具。

扫描 cleansed yaml 中所有"伤害修饰 pattern",统计每张卡 effect_text 中
潜在的 modifier 数量上界,为 §B.3 RL obs 中 K_mod (modifier list 上界)
定 scientific 起步值。

修饰 pattern 分类:
  - "+N 伤害" / "造成的伤害 +N" — flat add boost
  - "*N" / "翻倍" — mul boost (GI TCG 当前无,只为 future-proof)
  - "减少 N 点伤害" — flat reduce buff
  - "免疫" — immunity
  - "护盾" — shield (per stack 一次消耗)
  - "反应额外" — reaction boost (蕴种印 / 班尼特领域 等)

每张卡 effect_text 内出现的 pattern 数 = 该卡参与的 damage call 中可能的
modifier 数上界(实际运行时多 hook 同时机叠加可超过,但静态分析给起步)。

输出:
  - 单卡最高 modifier pattern 数 (P95/P99)
  - 分布直方图
  - top-N 高 pattern 卡列表

注意:
  这是**静态**分析,只看 effect_text 文本中 pattern 出现频次,不是实际
  运行时多 hook 叠加结果。准确数据需要 §B.2 落地后跑训练 replay log
  动态统计(届时本工具扩展添加 dynamic mode)。
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml


# ADR-0019 §B.2 modifier kind 对照
PATTERNS = {
    'ModBoostAdd_dmg_plus': re.compile(r'伤害\s*\+\s*\d+|\+\s*\d+\s*点?伤害'),
    'ModBoostAdd_reaction': re.compile(r'反应.*?\+\s*\d+|引发.*反应.*\+\s*\d+'),
    'ModBoostMul_double': re.compile(r'翻倍|双倍|\*\s*\d+'),
    'ModBoostType_enchant': re.compile(r'变为.*?元素伤害|附魔'),
    'ModReduce_flat': re.compile(r'伤害\s*-\s*\d+|减少.*?\d+\s*点?伤害|减半'),
    'ModShield': re.compile(r'护盾|抵消.*?\d+\s*点'),
    'ModImmunity': re.compile(r'免疫|不会(造成|受到)伤害'),
}


def scan_text(text: str) -> dict[str, int]:
    """统计 effect_text 中各 pattern 出现次数。"""
    if not text:
        return {}
    out = {}
    for kind, pat in PATTERNS.items():
        n = len(pat.findall(text))
        if n > 0:
            out[kind] = n
    return out


def collect_card_modifiers(yaml_path: Path) -> tuple[str, dict[str, int]]:
    """单卡 yaml 中所有 skill / talent / status 的 effect_text pattern 汇总。"""
    with open(yaml_path, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if data is None:
        return yaml_path.stem, {}

    name = data.get('name', yaml_path.stem)
    aggregated: Counter[str] = Counter()

    def consume(node):
        if isinstance(node, dict):
            for k in ('effect_text', 'text'):
                if k in node and isinstance(node[k], str):
                    for kind, n in scan_text(node[k]).items():
                        aggregated[kind] += n
            for v in node.values():
                consume(v)
        elif isinstance(node, list):
            for item in node:
                consume(item)

    consume(data)
    return name, dict(aggregated)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cleansed', default='data/cleaned', help='cleansed yaml root')
    ap.add_argument('--top', type=int, default=20, help='top-N highest modifier-count cards to list')
    args = ap.parse_args()

    root = Path(args.cleansed)
    if not root.exists():
        print(f'cleansed dir not found: {root}', file=sys.stderr)
        sys.exit(1)

    per_card_total: list[tuple[str, int, dict[str, int]]] = []  # (name, total_modifier_count, per_kind)
    kind_global = Counter()
    yaml_files = sorted(root.rglob('*.yaml'))

    for p in yaml_files:
        if p.name.startswith('_'):  # skip _glossary.yaml etc
            continue
        try:
            name, mods = collect_card_modifiers(p)
        except Exception as e:
            print(f'skip {p}: {e}', file=sys.stderr)
            continue
        total = sum(mods.values())
        if total > 0:
            per_card_total.append((name, total, mods))
            for kind, n in mods.items():
                kind_global[kind] += n

    # Sort
    per_card_total.sort(key=lambda x: -x[1])
    total_cards = len(per_card_total)

    # Distribution histogram
    histogram: Counter[int] = Counter()
    for _, total, _ in per_card_total:
        histogram[total] += 1

    # Percentiles
    counts_sorted = sorted([t for _, t, _ in per_card_total])
    n = len(counts_sorted)

    def pct(p: float) -> int:
        if n == 0:
            return 0
        idx = int(n * p)
        if idx >= n:
            idx = n - 1
        return counts_sorted[idx]

    print(f'=== ADR-0019 §B.0 modifier frequency static scan ===')
    print(f'cards scanned (with ≥1 modifier): {total_cards}')
    print(f'total modifier instances:         {sum(kind_global.values())}')
    print()
    print('--- per-kind global counts ---')
    for kind, n_kind in kind_global.most_common():
        print(f'  {kind:30s}  {n_kind}')
    print()
    print('--- per-card modifier-count percentiles ---')
    for p, label in [(0.50, 'P50'), (0.75, 'P75'), (0.90, 'P90'), (0.95, 'P95'), (0.99, 'P99'), (1.00, 'MAX')]:
        print(f'  {label}: {pct(p)}')
    print()
    print('--- distribution histogram (modifier-count → cards) ---')
    for cnt in sorted(histogram.keys()):
        bar = '#' * min(60, histogram[cnt])
        print(f'  {cnt:3d}: {histogram[cnt]:4d}  {bar}')
    print()
    print(f'--- top-{args.top} highest modifier-count cards ---')
    for name, total, mods in per_card_total[: args.top]:
        kind_str = ', '.join(f'{k}={v}' for k, v in mods.items())
        print(f'  {total:3d}  {name:30s}  ({kind_str})')
    print()
    print('=== K_mod 推荐起步 ===')
    print(f'  保守 (P95): {pct(0.95)}')
    print(f'  激进 (P99): {pct(0.99)}')
    print(f'  全覆盖 (MAX): {pct(1.00)}')
    print()
    print('注: 静态分析给起步,实际运行时多 hook 同时机叠加可超过此值。')
    print('§B.2 落地后跑训练 replay log 动态统计 modifier 数,refine K_mod。')


if __name__ == '__main__':
    main()
