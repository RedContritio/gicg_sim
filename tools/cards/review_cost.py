"""扫描所有 raw 卡,对每张应用 cost_from_slots 严格验证;生成 outlier multi-source 对照报告。

当前实现从历史外部 checkout ``~/Documents/gicg_sim/data/raw`` 读取
raw 数据，并与仓库内 ``data/cleaned`` 对照。

输出 markdown 表格,user review 后写 cost_overrides.yaml。
长期保留(每次 cost mapping/judgement/list 数据更新后都需重跑 review)。

raw 遍历 / parent_class 检测拆出至 review_cost_iter.py。本文件留 evaluate_slot
+ render + main。

用法(从 repo root)::

    .venv/bin/python -m tools.cards.review_cost
    .venv/bin/python -m tools.cards.review_cost --output /tmp/cost_review.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from tools.cards.constants import load_cost_bg_mapping, load_judgement
from tools.cards.cost_resolve import skill_cost_template
from tools.cards.extractors import (
    extract_cost_icon_url,
    extract_energy_icon_url,
    url_hash,
)
from tools.cards.list_ext import load_list_ext_index
from tools.cards.review_cost_iter import (
    get_character_element,
    iter_skill_slots,
    parent_class_of,
    parse_attr,
)

RAW_BASE = Path('/Users/redcontritio/Documents/gicg_sim/data/raw')
CLEANED_BASE = Path('data/cleaned')


def evaluate_slot(
    slot: dict,
    parent_class: str,
    element: str,
    entry_cost_h: str,
    entry_energy_h: str,
    list_ext: dict,
    attr_花费: int | None,
    bg_kind: dict,
    judgements: dict,
) -> dict | None:
    """对一个 slot 评估,返回 outlier dict;无 outlier 返回 None。"""
    life, life_bg = slot['life'], slot['life_bg']
    energy, energy_bg = slot['energy'], slot['energy_bg']

    use_hash = slot['kind'] in ('action', 'talent')
    issues = []

    list_cost_h = url_hash(list_ext.get('cost_icon_url', '')) if list_ext else ''
    list_energy_h = url_hash(list_ext.get('energy_icon_url', '')) if list_ext else ''
    if use_hash:
        if entry_cost_h and list_cost_h and entry_cost_h != list_cost_h:
            issues.append(f'entry cost hash≠list cost hash: {entry_cost_h} vs {list_cost_h}')
        if entry_energy_h and list_energy_h and entry_energy_h != list_energy_h:
            issues.append(f'entry energy hash≠list energy hash')

    cost: dict[str, int] = {}
    energy_req = 0
    primary_ok = True
    for n, bg, eh, lh, lbl in [
        (life, life_bg, entry_cost_h if use_hash else '', list_cost_h if use_hash else '', 'slot1'),
        (energy, energy_bg, entry_energy_h if use_hash else '', list_energy_h if use_hash else '', 'slot2'),
    ]:
        if bg not in bg_kind:
            issues.append(f'{lbl}: 主源未知 bg={bg}')
            primary_ok = False
            continue
        kind = bg_kind[bg]
        if kind is None:
            if n != 0 and bg != 13:
                issues.append(f'{lbl}: bg={bg} 空但 n={n}')
                primary_ok = False
            continue
        h = eh or lh
        sec = judgements.get(h) if h else None
        if sec is not None and sec != ('能量需求', n) and (sec[0] != kind or sec[1] != n):
            issues.append(f'{lbl}: 主源 ({kind},{n}) vs 备源 hash={h}→{sec}')
        if kind == '能量需求':
            energy_req += n
        else:
            cost[kind] = cost.get(kind, 0) + n

    cost_total = sum(cost.values()) if primary_ok else None

    list_filter_花费 = list_ext.get('filter_花费') if list_ext else None
    if cost_total is not None and list_filter_花费 is not None and list_filter_花费 != cost_total:
        issues.append(f'list filter 花费={list_filter_花费} vs cost 总数={cost_total}')

    if cost_total is not None and attr_花费 is not None and attr_花费 != cost_total:
        issues.append(f"attr['花费']={attr_花费} vs cost 总数={cost_total}")

    tpl_cost = tpl_eq = None
    if parent_class == 'character' and slot['kind'] == 'standard_skill' and primary_ok:
        tpl_cost, tpl_eq = skill_cost_template(slot['skill_type'], element, life, energy)
        if tpl_cost is not None:
            if tpl_cost != cost or tpl_eq != energy_req:
                issues.append(
                    f'skill 模板 ({slot["skill_type"]}/{element})→cost={tpl_cost},eq={tpl_eq} vs 实际 cost={cost},eq={energy_req}'
                )

    if not issues:
        return None
    return {
        'slot': slot,
        'parent_class': parent_class,
        'element': element,
        'cost_推断': cost,
        'energy_req_推断': energy_req,
        'entry_cost_hash': entry_cost_h,
        'entry_energy_hash': entry_energy_h,
        'list_cost_hash': list_cost_h,
        'list_energy_hash': list_energy_h,
        'list_cost_judge': judgements.get(entry_cost_h) if entry_cost_h else None,
        'list_filter_text': list_ext.get('filter_text', '') if list_ext else '',
        'list_filter_花费': list_filter_花费,
        'attr_花费': attr_花费,
        'tpl_cost': tpl_cost,
        'tpl_energy_req': tpl_eq,
        'issues': issues,
    }


def lookup_sonnet_cost(parent_class: str, fname: str) -> str:
    """Read the historical reference cost from ``data/cleaned`` when present."""
    p = CLEANED_BASE / parent_class / fname
    if not p.exists():
        return ''
    try:
        doc = yaml.safe_load(p.read_text(encoding='utf-8'))
    except Exception:
        return ''
    if isinstance(doc, dict):
        c = doc.get('cost')
        if c:
            return str(c)
        skills = doc.get('skills') or []
        if skills:
            return f'skills[0].cost={skills[0].get("cost")}'
    return ''


def render_markdown(outliers: list[dict]) -> str:
    lines = []
    lines.append(f'# Cost Outlier Review ({len(outliers)} 个 slot 不一致)\n')
    lines.append(f'生成于:全 raw 跑通后的 cost_from_slots 严格验证 raise 列表。\n')
    lines.append('每条对应 cost_overrides.yaml 一条 override(完整签名 + result + conflict_details)。\n\n')

    by_card: dict[str, list[dict]] = {}
    for o in outliers:
        card = o['card_id']
        by_card.setdefault(card, []).append(o)

    for card_id in sorted(by_card.keys()):
        items = by_card[card_id]
        lines.append(f'\n## {card_id}\n')
        for i, o in enumerate(items, 1):
            slot = o['slot']
            lines.append(
                f'\n### slot[{i}] {slot["kind"]} `{slot.get("name", "")}` (skill_type={slot["skill_type"]!r})\n'
            )
            lines.append('| 信息源 | 值 |')
            lines.append('|--------|----|')
            lines.append(
                f'| raw 4 字段 | life={slot["life"]} life_bg={slot["life_bg"]} energy={slot["energy"]} energy_bg={slot["energy_bg"]} |'
            )
            lines.append(f'| character.element | `{o["element"]!r}` |')
            lines.append(f'| entry_page costBgIcon hash | `{o["entry_cost_hash"] or "<none>"}` |')
            lines.append(f'| entry_page energyBgIcon hash | `{o["entry_energy_hash"] or "<none>"}` |')
            lines.append(f'| list API costBgIcon hash | `{o["list_cost_hash"] or "<none>"}` |')
            lines.append(f'| list API energyBgIcon hash | `{o["list_energy_hash"] or "<none>"}` |')
            lines.append(f'| (entry hash → judgement) | `{o["list_cost_judge"]}` |')
            lines.append(f'| list filter.text | `{o["list_filter_text"]}` |')
            lines.append(f'| list filter 花费 N | `{o["list_filter_花费"]}` |')
            lines.append(f"| attr['花费'] | `{o['attr_花费']}` |")
            lines.append(f'| skill 模板 expected | cost=`{o["tpl_cost"]}`, energy_req=`{o["tpl_energy_req"]}` |')
            lines.append(f'| **mapping 推断 cost** | `{o["cost_推断"]}`, energy_req=`{o["energy_req_推断"]}` |')
            lines.append(f'| sonnet cleaned cost | `{o.get("sonnet_cost", "")}` |')
            lines.append('\n**冲突**:')
            for iss in o['issues']:
                lines.append(f'- {iss}')
            lines.append('')

    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='/tmp/cost_review.md')
    args = ap.parse_args()

    bg_kind = load_cost_bg_mapping()
    judgements = load_judgement()
    list_ext_index = load_list_ext_index()

    outliers: list[dict] = []
    for sub in ('character', 'action', 'monster'):
        d = RAW_BASE / sub
        if not d.is_dir():
            continue
        for fp in sorted(d.glob('*.json')):
            if fp.name == '_index.json':
                continue
            raw_text = fp.read_text(encoding='utf-8')
            try:
                raw = json.loads(raw_text)
            except json.JSONDecodeError:
                continue
            pc = parent_class_of(raw)
            cid = raw.get('id')
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                continue
            list_ext = list_ext_index.get(cid_int) or {}

            element = get_character_element(raw) if pc in ('character', 'monster') else ''
            entry_cost_h = url_hash(extract_cost_icon_url(raw_text))
            entry_energy_h = url_hash(extract_energy_icon_url(raw_text))

            attr_花费 = None
            for m in raw.get('modules', []) or []:
                if m.get('name') != '基础信息':
                    continue
                for c in m.get('components', []) or []:
                    try:
                        dat = json.loads(c.get('data', '{}'))
                    except json.JSONDecodeError:
                        continue
                    a = parse_attr(dat)
                    for v in a.get('花费') or []:
                        if v.isdigit():
                            attr_花费 = int(v)
                            break

            for slot in iter_skill_slots(raw, pc):
                eff_element = element
                eff_skill_type = slot['skill_type']
                if slot['kind'] == 'variant_skill' or pc == 'monster':
                    eff_skill_type = ''
                    eff_element = ''
                slot_eval = dict(slot)
                slot_eval['skill_type'] = eff_skill_type
                o = evaluate_slot(
                    slot_eval, pc, eff_element, entry_cost_h, entry_energy_h, list_ext, attr_花费, bg_kind, judgements
                )
                if o is not None:
                    o['card_id'] = f'{sub}/{fp.name}'
                    o['raw_path'] = str(fp)
                    o['sonnet_cost'] = lookup_sonnet_cost(pc, fp.name.replace('.json', '.yaml'))
                    outliers.append(o)

    md = render_markdown(outliers)
    Path(args.output).write_text(md, encoding='utf-8')
    print(f'写入 {args.output}: {len(outliers)} outlier slots', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
