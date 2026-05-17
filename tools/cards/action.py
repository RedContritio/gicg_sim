"""raw action JSON → full yaml dict transformer。"""

from __future__ import annotations

import json
from pathlib import Path

from tools.cards.cost_resolve import cost_from_slots
from tools.cards.extractors import (
    extract_battle_action,
    extract_cost_icon_url,
    extract_deck_constraint,
    extract_duration,
    extract_energy_icon_url,
    extract_for_character,
    extract_generated_by,
    extract_weapon_type,
    url_hash,
)
from tools.cards.html_utils import html_to_multiline_text
from tools.cards.parse import consume_module, parse_attr
from tools.cards.terms import extract_terms, find_term_refs
from tools.cards.tracker import PathTracker


def _walk_action_modules(raw: dict, tracker: PathTracker) -> dict:
    """遍历 modules,按 effect_html 出现次数分标准 / 自行巧局。"""
    state: dict = {
        'attr_dict': {},
        'effect_html': '',
        'flavor_html': '',
        'flavor_text': '',
        'raw_life': 0,
        'raw_energy': 0,
        'raw_life_bg': 0,
        'raw_energy_bg': 0,
        'common_img': '',
        'gold_img': '',
        'var_effect_html': '',
        'n_effect_seen': 0,
    }
    for module in raw.get('modules', []) or []:
        mname, decoded = consume_module(module, tracker, 'modules[*]')
        if mname == '基础信息':
            for d in decoded:
                if 'attr' in d and not state['attr_dict']:
                    state['attr_dict'] = parse_attr(d['attr'], tracker, 'modules[*].components[*].data.attr')
                state['raw_life'] = state['raw_life'] or d.get('life', 0)
                state['raw_energy'] = state['raw_energy'] or d.get('energy', 0)
                state['raw_life_bg'] = state['raw_life_bg'] or d.get('life_bg', 0)
                state['raw_energy_bg'] = state['raw_energy_bg'] or d.get('energy_bg', 0)
                state['common_img'] = state['common_img'] or d.get('common_img', '')
                state['gold_img'] = state['gold_img'] or d.get('gold_img', '')
        elif mname == '卡牌故事':
            for d in decoded:
                rt = d.get('rich_text', '')
                if rt and not state['flavor_html']:
                    state['flavor_html'] = rt
                    state['flavor_text'] = html_to_multiline_text(rt)
        else:
            for d in decoded:
                rt = d.get('rich_text', '')
                if not rt or rt.strip() in ('', '<p></p>'):
                    continue
                if state['n_effect_seen'] == 0:
                    state['effect_html'] = rt
                elif state['n_effect_seen'] == 1 and not state['var_effect_html']:
                    state['var_effect_html'] = rt
                state['n_effect_seen'] += 1
    return state


def _detect_action_jiqiao(raw: dict, n_effect_seen: int) -> bool:
    """A-3+C-8 双向契约:同时检查 (a) effect 出现 >1 次 + (b) 无名 module rich_text 含 '自行巧局'。

    两路一致 → 接受;只命中一路 → raise。
    """
    has_dup_effect = n_effect_seen > 1
    has_jiqiao_text = False
    for m in raw.get('modules', []) or []:
        if m.get('name'):
            continue
        for c in m.get('components', []) or []:
            data = c.get('data', '')
            if not data:
                continue
            try:
                d = json.loads(data)
            except json.JSONDecodeError:
                continue
            if '自行巧局' in d.get('rich_text', ''):
                has_jiqiao_text = True
    if has_dup_effect != has_jiqiao_text:
        raise ValueError(
            f"_detect_action_jiqiao: 双路检查不一致 (n_effect_seen>1={has_dup_effect}, '自行巧局' text={has_jiqiao_text})"
        )
    return has_dup_effect


def transform_action(raw: dict, raw_path: Path, raw_text: str, tracker: PathTracker, list_ext: dict) -> dict:
    """raw action JSON → 规范化 dict。

    cost 全源严格交叉验证:raw 4 字段 + entry_page hash + list API hash + list filter 花费 + attr 花费。
    任一不一致 raise(由 user 在 cost_overrides.yaml 显式 override)。
    """
    for k in ('id', 'name', 'desc', 'icon_url', 'header_img_url', 'version'):
        tracker.visit(k)
    for _ in raw.get('menus', []) or []:
        tracker.visit('menus[*].name')

    s = _walk_action_modules(raw, tracker)
    attr_dict = s['attr_dict']
    effect_html = s['effect_html']

    sub_class = (attr_dict.get('类型') or [''])[0]
    tags = attr_dict.get('标签') or []
    cost_text_raw = (attr_dict.get('花费') or [''])[0]
    icon_url_cost = extract_cost_icon_url(raw_text)
    icon_url_energy = extract_energy_icon_url(raw_text)
    attr_花费_total = int(cost_text_raw) if cost_text_raw.isdigit() else None
    cost, energy_req = cost_from_slots(
        s['raw_life'],
        s['raw_life_bg'],
        s['raw_energy'],
        s['raw_energy_bg'],
        entry_cost_hash=url_hash(icon_url_cost),
        entry_energy_hash=url_hash(icon_url_energy),
        list_cost_hash=url_hash(list_ext.get('cost_icon_url', '')),
        list_energy_hash=url_hash(list_ext.get('energy_icon_url', '')),
        list_filter_花费=list_ext.get('filter_花费'),
        attr_花费_total=attr_花费_total,
    )

    text_multiline = html_to_multiline_text(effect_html)
    terms = extract_terms(effect_html)
    term_refs = find_term_refs(effect_html)
    duration = extract_duration(text_multiline)
    # A-5+A-6 信赖 text-based(wiki tag schema 多样,'天赋'/'特技'/'其他标签' 都可能含 weapon/character anchor;
    # text 命中 = 真有该限定,接受不论 tag)
    weapon_type = extract_weapon_type(text_multiline)
    for_character = extract_for_character(text_multiline)
    deck_constraint = extract_deck_constraint(text_multiline)
    is_combat_action = bool(extract_battle_action(effect_html))

    out: dict = {
        'id': int(raw['id']) if str(raw.get('id', '')).isdigit() else raw.get('id', ''),
        'name': raw.get('name', ''),
        'parent_class': 'action',
        'desc': raw.get('desc', ''),
        'sub_class': sub_class,
        'tags': tags,
        'cost_text': cost_text_raw,
        'cost': cost,
        'icon_url': raw.get('icon_url', ''),
        'header_img_url': raw.get('header_img_url', ''),
        'version': raw.get('version', ''),
        'attr': attr_dict,
        'raw_life': s['raw_life'],
        'raw_life_bg': s['raw_life_bg'],
        'raw_energy': s['raw_energy'],
        'raw_energy_bg': s['raw_energy_bg'],
        'effect_html': effect_html,
        'effect_text': text_multiline,
        'term_refs': term_refs,
        'terms': terms,
        'cost_bg_icon_url': icon_url_cost,
    }
    if energy_req:
        out['energy_req'] = energy_req
    if duration:
        out['duration'] = duration
    if weapon_type:
        out['weapon_type'] = weapon_type
    if for_character:
        # 唯一 key:requires_char(与 gicg_engine DSL 一致;sonnet 历史用 for_character 由对拍脚本做 alias map)
        out['requires_char'] = for_character
    if deck_constraint:
        out['deck_constraint'] = deck_constraint
    if is_combat_action:
        out['is_combat_action'] = True
    from tools.cards.constants import get_acquire

    acquire_a = get_acquire(attr_dict)
    generated_by = extract_generated_by(acquire_a)
    if generated_by:
        out['generated_by'] = generated_by
    if s['var_effect_html']:
        out['variants'] = [
            {'mode': '标准', 'effect_html': effect_html, 'effect_text': text_multiline},
            {
                'mode': '自行巧局',
                'effect_html': s['var_effect_html'],
                'effect_text': html_to_multiline_text(s['var_effect_html']),
            },
        ]
    if s['common_img']:
        out['common_img'] = s['common_img']
    if s['gold_img']:
        out['gold_img'] = s['gold_img']
    if _detect_action_jiqiao(raw, s['n_effect_seen']):
        out['jiqiao'] = True
    out['flavor_html'] = s['flavor_html']
    out['flavor_text'] = s['flavor_text']
    out['_raw_path'] = str(raw_path)
    return out
