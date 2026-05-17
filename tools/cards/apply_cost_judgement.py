"""把 user 在 data/cost_icons/_judgement.yaml 中填的判定批量应用到 data/full/action/*.yaml。

判定文本格式(中文紧凑):
    同色 N        →  cost = {same: N}
    无色 N        →  cost = {any: N}
    <元素>N       →  cost = {<元素>: N}  (元素 ∈ 风/火/雷/冰/水/草/岩)
    mixed         →  跳过(case-by-case)

应用时:
- 删除原 cost 字段、cost_text、cost_unsure
- 写入 cost_text(规范化字符串)+ cost(dict)
- 保留 cost_bg_icon_url
- 不动其它字段

干跑模式:--dry-run 只打印 plan,不写。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ELEMENTS = {'风', '火', '雷', '冰', '水', '草', '岩'}

JUDGE_RE = re.compile(r'^\s*([\u4e00-\u9fff]+|mixed)\s*[:：]?\s*(\d+)?\s*$')


def parse_judgement(s: str) -> tuple[str, int] | None:
    """'同色 1' / '无色 2' / '火 3' / '火3' / 'mixed' → (kind, N).
    kind ∈ {same, any, <元素>, mixed}, N ∈ int (mixed → 0)."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if s.startswith('mixed'):
        return ('mixed', 0)

    m = JUDGE_RE.match(s)
    if not m:
        # Try alternative: "无色4" jammed together
        m = re.match(r'^([\u4e00-\u9fff]+?)(\d+)$', s)
    if not m:
        return None

    word, num = m.group(1), m.group(2)
    n = int(num) if num else 0
    if word == '同色':
        return ('same', n)
    if word in ('无色', '任意'):
        return ('any', n)
    if word in ELEMENTS:
        return (word, n)
    return None


def build_cost(kind: str, n: int) -> tuple[dict, str]:
    # 忠实 user 判定的语义。N=0 时 same/any 数学等价但保留语义。
    if kind == 'same':
        return {'same': n}, f'{n}同色' if n > 0 else '0同色'
    if kind == 'any':
        return {'any': n}, f'{n}任意' if n > 0 else '0'
    if kind in ELEMENTS:
        return {kind: n}, f'{n}{kind}'
    raise ValueError(f'unknown kind {kind!r}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    icons_dir = Path('data/cost_icons')
    full_action = Path('data/full/action')

    judgement_doc = yaml.safe_load(open(icons_dir / '_judgement.yaml', encoding='utf-8'))
    index_doc = yaml.safe_load(open(icons_dir / '_index.yaml', encoding='utf-8'))
    mapping = yaml.safe_load(open(icons_dir / '_mapping.yaml', encoding='utf-8'))

    judgements = judgement_doc.get('judgements', {}) or {}

    # 先 parse 每个 NN 的判定
    parsed: dict[str, tuple[str, int]] = {}
    bad: list[tuple[str, str]] = []
    for nn, raw in judgements.items():
        if raw is None:
            continue
        # nn 可能是 int(yaml 1-9 / leading zero) 或 str
        nn_s = f'{int(nn):02d}' if isinstance(nn, int) else str(nn).strip()
        p = parse_judgement(str(raw))
        if p is None:
            bad.append((nn_s, str(raw)))
        else:
            parsed[nn_s] = p

    if bad:
        print('未解析的判定:', file=sys.stderr)
        for nn, raw in bad:
            print(f'  {nn}: {raw!r}', file=sys.stderr)
        print('', file=sys.stderr)

    # 收集 hash → judgement
    h2judge: dict[str, tuple[str, int]] = {}
    for nn, judge in parsed.items():
        h = index_doc[nn]['hash']
        h2judge[h] = judge

    # 遍历 full/action,找每个 yaml 对应的 hash
    n_changed = 0
    n_mixed = 0
    n_no_match = 0
    for yp in sorted(full_action.glob('*.yaml')):
        with open(yp, encoding='utf-8') as f:
            try:
                card = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                print(f'  ✗ {yp}: {e}', file=sys.stderr)
                continue

        cid = str(card.get('id', yp.stem.split('_')[0]))
        # 找此卡的 hash:从 mapping 反查
        h = ''
        for hh, lst in mapping.items():
            if any(str(c.get('id')) == cid for c in lst):
                h = hh
                break
        if not h:
            continue
        if h not in h2judge:
            n_no_match += 1
            continue

        kind, n = h2judge[h]
        if kind == 'mixed':
            n_mixed += 1
            print(f'  [mixed-skip] {cid} {card.get("name", "")}', file=sys.stderr)
            continue

        # Sanity:dl_cost_icons 可能把 specialty / variants 的 cost icon 错指给顶层(取 fe_ext 第一个 URL)。
        # 顶层卡的 raw attr.花费(原始 cost 数字)若与判定 N 不一致 → 数据矛盾,skip 顶层 override。
        attr = card.get('attr', {}) or {}
        raw_cost_strs = attr.get('花费', []) or []
        if raw_cost_strs and isinstance(raw_cost_strs[0], str):
            m = re.match(r'^\s*[:：]?\s*(\d+)', raw_cost_strs[0])
            if m and int(m.group(1)) != n:
                print(
                    f'  [skip-mismatch] {cid} {card.get("name", "")} attr.花费={raw_cost_strs[0]!r} '
                    f'但 judge N={n}(hash={h[:8]}) — mapping 可能错配 specialty/variant icon',
                    file=sys.stderr,
                )
                continue

        new_cost, new_text = build_cost(kind, n)
        old_cost = card.get('cost', {})
        old_text = card.get('cost_text', '')
        had_unsure = 'cost_unsure' in card

        if old_cost == new_cost and old_text == new_text and not had_unsure:
            continue  # nothing to do

        if not args.dry_run:
            # 直接修改顶层字段,深嵌套 attached_special.cost / variants[].cost 不动。
            card['cost'] = new_cost
            card['cost_text'] = new_text
            card.pop('cost_unsure', None)
            with open(yp, 'w', encoding='utf-8') as f:
                yaml.safe_dump(card, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        n_changed += 1
        print(f'  {cid:>7} {card.get("name", "")[:14]:<14} {old_cost} → {new_cost}')

    print(f'\nchanged={n_changed}  mixed-skipped={n_mixed}  no-judgement={n_no_match}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
