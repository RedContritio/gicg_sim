"""raw → cost slot 遍历工具 — 给 review_cost 提供 per-card / per-slot iteration。

从 review_cost.py 拆出。负责把 raw JSON 拆成可独立 evaluate 的 slot dict 序列。
"""

from __future__ import annotations

import json

ELEM_TOKEN_TO_ELEMENT = {f'{e}元素': e for e in ['风', '火', '雷', '冰', '水', '草', '岩']}


def parse_attr(d: dict) -> dict:
    out = {}
    for kv in d.get('attr', []) or []:
        k = kv.get('key', '').rstrip('：:').strip()
        if not k:
            continue
        out[k] = [v.lstrip('：:').strip() for v in (kv.get('value') or [])]
    return out


def get_character_element(raw: dict) -> str:
    for m in raw.get('modules', []) or []:
        if m.get('name') != '基础信息':
            continue
        for c in m.get('components', []) or []:
            try:
                d = json.loads(c.get('data', '{}'))
            except json.JSONDecodeError:
                continue
            attr = parse_attr(d)
            for v in attr.get('元素') or []:
                e = ELEM_TOKEN_TO_ELEMENT.get(v.strip())
                if e:
                    return e
    return ''


def parent_class_of(raw: dict) -> str:
    for menu in raw.get('menus', []) or []:
        n = menu.get('name', '')
        if n == '角色牌':
            return 'character'
        if n == '行动牌':
            return 'action'
        if n == '魔物牌':
            return 'monster'
    return ''


def iter_skill_slots(raw: dict, parent_class: str):
    """Yield one dict per cost-slot evaluation.

    Each entry includes kind, life/life_bg, energy/energy_bg, skill type,
    and related fields. A card may contribute standard skills, variants,
    a talent, or its top-level action cost.
    """
    if parent_class in ('character', 'monster'):
        seen = 0
        for m in raw.get('modules', []) or []:
            mname = m.get('name', '')
            if mname == '卡牌技能':
                seen += 1
                is_var = seen >= 2
                for c in m.get('components', []) or []:
                    try:
                        d = json.loads(c.get('data', '{}'))
                    except json.JSONDecodeError:
                        continue
                    for sk in d.get('list', []) or []:
                        if not sk.get('tab_name'):
                            continue
                        yield {
                            'kind': 'variant_skill' if is_var else 'standard_skill',
                            'name': sk.get('tab_name'),
                            'skill_type': sk.get('skill_type', ''),
                            'life': sk.get('life', 0),
                            'life_bg': sk.get('life_bg', 0),
                            'energy': sk.get('energy', 0),
                            'energy_bg': sk.get('energy_bg', 0),
                        }
            elif mname == '天赋牌':
                for c in m.get('components', []) or []:
                    try:
                        d = json.loads(c.get('data', '{}'))
                    except json.JSONDecodeError:
                        continue
                    for t in d.get('list', []) or []:
                        if not t.get('tab_name'):
                            continue
                        yield {
                            'kind': 'talent',
                            'name': t.get('tab_name'),
                            'skill_type': '装备牌',
                            'life': t.get('life', 0),
                            'life_bg': t.get('life_bg', 0),
                            'energy': t.get('energy', 0),
                            'energy_bg': t.get('energy_bg', 0),
                        }
    elif parent_class == 'action':
        for m in raw.get('modules', []) or []:
            if m.get('name') != '基础信息':
                continue
            for c in m.get('components', []) or []:
                try:
                    d = json.loads(c.get('data', '{}'))
                except json.JSONDecodeError:
                    continue
                yield {
                    'kind': 'action',
                    'name': raw.get('name', ''),
                    'skill_type': '',
                    'life': d.get('life', 0),
                    'life_bg': d.get('life_bg', 0),
                    'energy': d.get('energy', 0),
                    'energy_bg': d.get('energy_bg', 0),
                }
