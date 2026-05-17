"""按机制 bucket 关键词分类全 effect_text,显式审视长尾 — 替代 frequency-based audit。

frequency-based 方法(audit_effect_patterns.py)按句子 normalize 后 freq 统计,
top-N 漏长尾(boss / 神级卡的复杂机制只出现 1-2 次但是真 ★★★ requirements)。

本 audit 按 **mechanism bucket** 分类(trigger / effect / condition / target / meta),
每个 bucket 用关键词集触发,扫**全部** 1348 effect blocks。同一 effect 可属多个 bucket。

输出每 bucket: 命中卡数 / 命中 effect block 数 / top + tail 例子(头 3 个 + 尾 5 个)。

Bucket 关键词集拆到 audit_effect_buckets.py(132 buckets)。

用法(从 repo root)::

    .venv/bin/python -m tools.cards.audit_effect_mechanisms
    .venv/bin/python -m tools.cards.audit_effect_mechanisms --output docs/3_plans/cards/effect_mechanism_inventory.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from tools.cards.audit_effect_buckets import (
    CONDITION_BUCKETS,
    EFFECT_BUCKETS,
    META_BUCKETS,
    TARGET_BUCKETS,
    TRIGGER_BUCKETS,
)

CLEANED = Path('data/cleaned')


def collect_effects() -> list[tuple[str, str, str]]:
    """yield (source_id, effect_kind, effect_text). source_id 含 sub_class + cid + name 用于 audit。"""
    out: list[tuple[str, str, str]] = []
    for sub in ('action', 'character', 'monster'):
        d = CLEANED / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob('*.yaml')):
            try:
                doc = yaml.safe_load(p.read_text(encoding='utf-8'))
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            cid = doc.get('id', p.stem)
            cname = doc.get('name', '')
            base = f'{sub}/{cid}_{cname}'
            t = doc.get('effect_text', '') or ''
            if t.strip():
                out.append((base, 'main', t))
            for kind in ('skills', 'summons'):
                for i, item in enumerate(doc.get(kind, []) or []):
                    if isinstance(item, dict):
                        t = item.get('effect_text', '') or ''
                        if t.strip():
                            out.append((base, f'{kind}[{i}]:{item.get("name", "")}', t))
            talent = doc.get('talent')
            if isinstance(talent, dict):
                t = talent.get('effect_text', '') or ''
                if t.strip():
                    out.append((base, 'talent', t))
    return out


def classify(text: str, bucket_defs: dict[str, list[str]]) -> set[str]:
    """对 text 应用所有 bucket 的关键词,返回命中 bucket 名集合。"""
    hits: set[str] = set()
    for name, patterns in bucket_defs.items():
        for pat in patterns:
            try:
                if re.search(pat, text):
                    hits.add(name)
                    break
            except re.error:
                continue
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='/tmp/effect_mech.md')
    ap.add_argument('--examples-per-bucket', type=int, default=8, help='per bucket 例子数(头 N 尾 N 各一半)')
    args = ap.parse_args()

    effects = collect_effects()
    print(f'collected {len(effects)} effect blocks', file=sys.stderr)

    # 按 bucket category 跑分类
    categories = [
        ('Trigger', TRIGGER_BUCKETS),
        ('Effect', EFFECT_BUCKETS),
        ('Condition', CONDITION_BUCKETS),
        ('Target', TARGET_BUCKETS),
        ('Meta', META_BUCKETS),
    ]

    bucket_hits: dict[str, dict[str, list[tuple[str, str, str]]]] = {}
    bucket_unique_cards: dict[str, dict[str, set[str]]] = {}
    for cat_name, defs in categories:
        bucket_hits[cat_name] = defaultdict(list)
        bucket_unique_cards[cat_name] = defaultdict(set)
        for src, kind, text in effects:
            hits = classify(text, defs)
            for b in hits:
                bucket_hits[cat_name][b].append((src, kind, text))
                bucket_unique_cards[cat_name][b].add(src)

    # 计算 unclassified — 未命中任何 bucket 的 effect block(可能是新长尾机制)
    all_classified_blocks: set[tuple[str, str]] = set()
    for cat_name, _ in categories:
        for b, hits in bucket_hits[cat_name].items():
            for src, kind, _ in hits:
                all_classified_blocks.add((src, kind))
    unclassified = []
    for src, kind, text in effects:
        if (src, kind) not in all_classified_blocks:
            unclassified.append((src, kind, text))

    # 生成 markdown
    lines: list[str] = []
    lines.append('# Effect Mechanism Inventory(全 1348 块,长尾覆盖)')
    lines.append('')
    lines.append(
        f'- 输入 effect blocks: **{len(effects)}**(action.main + char.skills/.summons/.talent + monster.skills/.summons)'
    )
    lines.append(
        f'- bucket 总数: **{sum(len(d) for _, d in categories)}** 个(Trigger {len(TRIGGER_BUCKETS)} / Effect {len(EFFECT_BUCKETS)} / Condition {len(CONDITION_BUCKETS)} / Target {len(TARGET_BUCKETS)} / Meta {len(META_BUCKETS)})'
    )
    lines.append(
        f'- 未命中任何 bucket 的 block: **{len(unclassified)}**(待 audit:可能是新机制或 bucket 关键词覆盖不全)'
    )
    lines.append('')
    lines.append('每 bucket 报: 命中 effect blocks 数 / 涉及 unique 卡数 / 头尾各 4 例。')
    lines.append('')

    for cat_name, defs in categories:
        lines.append(f'## {cat_name} buckets({len(defs)} 类)')
        lines.append('')
        sorted_names = sorted(defs.keys(), key=lambda n: -len(bucket_unique_cards[cat_name][n]))
        for name in sorted_names:
            hits = bucket_hits[cat_name][name]
            uniq = bucket_unique_cards[cat_name][name]
            lines.append(f'### {name}')
            lines.append(f'- 命中 blocks: **{len(hits)}** / 涉及卡: **{len(uniq)}**')
            n_per_side = max(1, args.examples_per_bucket // 2)
            head = hits[:n_per_side]
            tail = hits[-n_per_side:] if len(hits) > n_per_side * 2 else []
            if head:
                lines.append('- 头 examples:')
                for src, kind, text in head:
                    excerpt = text.replace('\n', ' ')[:120]
                    lines.append(f'  - `{src}#{kind}`: {excerpt}')
            if tail:
                lines.append('- 尾 examples(长尾):')
                for src, kind, text in tail:
                    excerpt = text.replace('\n', ' ')[:120]
                    lines.append(f'  - `{src}#{kind}`: {excerpt}')
            lines.append('')

    if unclassified:
        lines.append('## Unclassified blocks(待 audit)')
        lines.append('')
        lines.append(f'共 **{len(unclassified)}** 个 effect block 未命中任何 bucket。可能含:')
        lines.append('- 真新机制(bucket 关键词集没覆盖)')
        lines.append('- effect_text strip 残缺(HTML 残留 / term expansion 噪声)')
        lines.append('- 极短 effect(只是 metadata 描述)')
        lines.append('')
        lines.append('全列表(供 user audit):')
        lines.append('')
        for src, kind, text in unclassified[:60]:
            excerpt = text.replace('\n', ' ')[:140]
            lines.append(f'- `{src}#{kind}`: {excerpt}')
        if len(unclassified) > 60:
            lines.append(f'- ... +{len(unclassified) - 60} more')

    Path(args.output).write_text('\n'.join(lines), encoding='utf-8')
    print(f'written {args.output} ({len(lines)} lines)', file=sys.stderr)

    print('\n=== summary ===')
    for cat_name, defs in categories:
        total_hits = sum(len(bucket_hits[cat_name][n]) for n in defs)
        n_buckets_zero = sum(1 for n in defs if not bucket_hits[cat_name][n])
        print(f'  {cat_name}: {len(defs)} buckets, {total_hits} hits, {n_buckets_zero} zero-hit buckets')
    print(f'  Unclassified: {len(unclassified)} blocks')

    return 0


if __name__ == '__main__':
    sys.exit(main())
