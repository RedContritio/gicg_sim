"""raw character JSON → full yaml dict transformer。

build_* helpers 拆出至 character_builders.py;本文件留 _walk_modules 遍历 +
transform_character 主调度 + jiqiao 检测。
"""

from __future__ import annotations

from pathlib import Path

from tools.cards.character_builders import (
    build_character_skill,
    build_summon,
    build_talent,
)
from tools.cards.constants import get_acquire, load_elements
from tools.cards.cost_resolve import parse_energy_from_attr
from tools.cards.extractors import (
    extract_cost_icon_url,
    extract_energy_icon_url,
    url_hash,
)
from tools.cards.html_utils import html_to_multiline_text
from tools.cards.parse import consume_module, parse_attr, parse_skill_items
from tools.cards.terms import extract_terms
from tools.cards.tracker import PathTracker


def _set_once(state: dict, key: str, new_val, label: str) -> None:
    """设置 state[key] = new_val,若已设非空且与 new_val 不同 → raise。

    替代 `state[key] = state[key] or new_val` 的隐式 first-wins fallback。
    new_val 为 0 / '' 视为空,不覆盖已有非空值,但若已有非空值与新非空值不同 raise。
    """
    cur = state.get(key)
    if not new_val:
        return  # 空值不写
    if cur and cur != new_val:
        raise ValueError(f'_walk_modules: state[{key!r}] 多次写入冲突 ({label}):{cur!r} vs {new_val!r}')
    state[key] = new_val


def _walk_modules(raw: dict, tracker: PathTracker) -> dict:
    """遍历 modules,分离标准 / 自行巧局(第二次出现的同名 module)。"""
    card_id = int(raw['id']) if str(raw.get('id', '')).isdigit() else 0
    state: dict = {
        'title': '',
        'attr_dict': {},
        'hp': 0,
        'energy_cap': 0,
        'skills_raw': [],
        'summons_raw': [],
        'talents_raw': [],
        'flavor_html': '',
        'flavor_text': '',
        'common_img': '',
        'gold_img': '',
        'raw_life_bg': 0,
        'raw_energy_bg': 0,
        'var_attr': {},
        'var_hp': 0,
        'var_energy': 0,
        'var_skills_raw': [],
        'var_summons_raw': [],
    }
    seen: set[str] = set()
    for module in raw.get('modules', []) or []:
        mname, decoded = consume_module(module, tracker, 'modules[*]')
        is_variant = mname in seen and mname != ''
        if not is_variant and mname:
            seen.add(mname)

        if mname == '基础信息':
            for d in decoded:
                if 'attr' in d:
                    parsed = parse_attr(d['attr'], tracker, 'modules[*].components[*].data.attr')
                    if is_variant and not state['var_attr']:
                        state['var_attr'] = parsed
                    elif not is_variant and not state['attr_dict']:
                        state['attr_dict'] = parsed
                if is_variant:
                    _set_once(state, 'var_hp', d.get('life', 0), 'variant base.life')
                    _set_once(state, 'var_energy', d.get('energy', 0), 'variant base.energy')
                else:
                    _set_once(state, 'title', d.get('name', ''), 'standard base.name')
                    _set_once(state, 'hp', d.get('life', 0), 'standard base.life')
                    _set_once(state, 'energy_cap', d.get('energy', 0), 'standard base.energy')
                    _set_once(state, 'common_img', d.get('common_img', ''), 'standard base.common_img')
                    _set_once(state, 'gold_img', d.get('gold_img', ''), 'standard base.gold_img')
                    _set_once(state, 'raw_life_bg', d.get('life_bg', 0), 'standard base.life_bg')
                    _set_once(state, 'raw_energy_bg', d.get('energy_bg', 0), 'standard base.energy_bg')
        elif mname == '卡牌技能':
            tgt = state['var_skills_raw'] if is_variant else state['skills_raw']
            for d in decoded:
                tgt.extend(parse_skill_items(d.get('list') or [], card_id=card_id, module_kind='卡牌技能'))
        elif mname == '召唤物':
            tgt = state['var_summons_raw'] if is_variant else state['summons_raw']
            for d in decoded:
                tgt.extend(parse_skill_items(d.get('list') or [], card_id=card_id, module_kind='召唤物'))
        elif mname == '天赋牌':
            for d in decoded:
                state['talents_raw'].extend(
                    parse_skill_items(d.get('list') or [], card_id=card_id, module_kind='天赋牌')
                )
        elif mname == '卡牌故事':
            for d in decoded:
                rt = d.get('rich_text', '')
                if rt and not state['flavor_html']:
                    state['flavor_html'] = rt
                    state['flavor_text'] = html_to_multiline_text(rt)
    return state


def _detect_jiqiao(walk_state: dict) -> bool:
    """character / monster jiqiao = 有真实 variant 内容(跟 has_real_variant 同信号)。

    历史尝试用"module 重复"信号 — 但 audit 表明 57 张 character 卡 wiki module 重复但
    variant module 内容全空(parse_skill_items 全 skip empty placeholder),即 wiki schema
    "module 重复"不等于"真有 variant"。真信号是 walk_state 的 var_* 数据非空。
    """
    return bool(
        walk_state.get('var_skills_raw')
        or walk_state.get('var_summons_raw')
        or walk_state.get('var_hp')
        or walk_state.get('var_energy')
    )


def transform_character(
    raw: dict,
    raw_path: Path,
    raw_text: str,
    tracker: PathTracker,
    list_ext: dict,
    is_monster: bool = False,
    hash_collector: dict | None = None,
) -> dict:
    for k in ('id', 'name', 'desc', 'icon_url', 'header_img_url', 'version'):
        tracker.visit(k)
    for _ in raw.get('menus', []) or []:
        tracker.visit('menus[*].name')

    s = _walk_modules(raw, tracker)

    elem_map = load_elements()
    element_full = (s['attr_dict'].get('元素') or [''])[0]
    if element_full and element_full not in elem_map:
        raise ValueError(f"未知元素 '{element_full}';请补 data/cards/elements.yaml")
    element = elem_map.get(element_full, '')
    weapon = (s['attr_dict'].get('武器') or [''])[0]
    faction = s['attr_dict'].get('阵营') or []
    energy_cap = parse_energy_from_attr(s['attr_dict']) or s['energy_cap']
    entry_cost_hash = url_hash(extract_cost_icon_url(raw_text))
    entry_energy_hash = url_hash(extract_energy_icon_url(raw_text))
    if hash_collector is not None and entry_cost_hash:
        hash_collector.setdefault(entry_cost_hash, []).append(
            {
                'card_id': int(raw['id']) if str(raw.get('id', '')).isdigit() else 0,
                'name': raw.get('name', ''),
                'raw_life': s['hp'],
                'raw_energy_cap': energy_cap,
            }
        )

    skills = [
        build_character_skill(x, element, entry_cost_hash, entry_energy_hash, is_monster=is_monster)
        for x in s['skills_raw']
    ]
    summons = [build_summon(x) for x in s['summons_raw']]
    talent = build_talent(s['talents_raw'][0], entry_cost_hash, entry_energy_hash) if s['talents_raw'] else None

    terms: dict[str, str] = {}
    for block in s['skills_raw'] + s['summons_raw'] + s['talents_raw']:
        for name, exp in extract_terms(block['desc_html']).items():
            if (prev := terms.get(name)) is None or len(exp) > len(prev):
                terms[name] = exp

    has_var_skills = bool(s['var_skills_raw'])
    has_var_summons = bool(s['var_summons_raw'])
    has_var_basic = s['var_hp'] > 0 or s['var_energy'] > 0
    has_real_variant = has_var_skills or has_var_summons or has_var_basic

    variants: list = []
    if has_real_variant:
        var: dict = {'mode': '自行巧局'}
        if s['var_hp']:
            var['hp'] = s['var_hp']
        if s['var_energy']:
            var['energy'] = s['var_energy']
        if s['var_attr']:
            var['attr'] = s['var_attr']
        if has_var_skills:
            var['skills'] = [
                build_character_skill(
                    x, element, entry_cost_hash, entry_energy_hash, is_variant=True, is_monster=is_monster
                )
                for x in s['var_skills_raw']
            ]
        if has_var_summons:
            var['summons'] = [build_summon(x) for x in s['var_summons_raw']]
        variants.append(var)

    acquire = get_acquire(s['attr_dict'])
    icon_url_cost = extract_cost_icon_url(raw_text)
    primordial = (s['attr_dict'].get('始基力') or [''])[0]

    out: dict = {
        'id': int(raw['id']) if str(raw.get('id', '')).isdigit() else raw.get('id', ''),
        'name': raw.get('name', ''),
        'title': s['title'],
        'parent_class': 'character',
        'desc': raw.get('desc', ''),
        'icon_url': raw.get('icon_url', ''),
        'header_img_url': raw.get('header_img_url', ''),
        'version': raw.get('version', ''),
        'attr': s['attr_dict'],
        'element': element,
        'weapon': weapon,
        'faction': faction,
        'hp': s['hp'],
        'energy': energy_cap,
    }
    if acquire:
        out['acquire'] = acquire
    if primordial:
        out['始基力'] = primordial
    if s['common_img']:
        out['common_img'] = s['common_img']
    if s['gold_img']:
        out['gold_img'] = s['gold_img']
    if s['raw_life_bg']:
        out['raw_life_bg'] = s['raw_life_bg']
    if s['raw_energy_bg']:
        out['raw_energy_bg'] = s['raw_energy_bg']
    if icon_url_cost:
        out['cost_bg_icon_url'] = icon_url_cost
    out['skills'] = skills
    out['summons'] = summons
    if talent:
        out['talent'] = talent
    if _detect_jiqiao(s):
        out['jiqiao'] = True
    if variants:
        out['variants'] = variants
    out['flavor_html'] = s['flavor_html']
    out['flavor_text'] = s['flavor_text']
    out['terms'] = terms
    out['_raw_path'] = str(raw_path)
    return out
