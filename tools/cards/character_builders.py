"""raw character/monster sub-block (skill / summon / talent) → 规范化 dict builders。

从 character.py 拆出。transform_character 调这些 builder 把每个 raw skill / summon /
talent slot 转成最终 yaml dict 中的一个条目。
"""

from __future__ import annotations

from tools.cards.cost_resolve import cost_from_slots
from tools.cards.extractors import (
    extract_battle_action,
    extract_deck_constraint,
    url_hash,
)
from tools.cards.html_utils import html_to_multiline_text


def build_character_skill(
    s: dict,
    element: str,
    entry_cost_hash: str,
    entry_energy_hash: str,
    is_variant: bool = False,
    is_monster: bool = False,
) -> dict:
    """raw skill → 规范化 dict。cost 全源严格交叉验证。

    源:raw 4 字段 mapping(主)+ skill_type+element 模板(仅 character standard skill 验证)。

    跳过模板验证的情形:
    - is_variant:自行巧局模式 cost 设计可能不同,wiki raw 也常缺
    - is_monster:怪物的"普攻"通常无元素 cost(只无色 2),不符合 character 模板
    """
    skip_template = is_variant or is_monster
    skill_icon_hash = url_hash(s.get('icon', ''))
    cost, energy_req = cost_from_slots(
        s['life'],
        s['life_bg'],
        s['energy'],
        s['energy_bg'],
        entry_cost_hash=entry_cost_hash,
        entry_energy_hash=entry_energy_hash,
        skill_icon_hash=skill_icon_hash,
        skill_type='' if skip_template else s['skill_type'],
        character_element='' if skip_template else element,
    )
    sk: dict = {
        'name': s['name'],
        'type': s['skill_type'],
        'raw_life': s['life'],
        'raw_life_bg': s['life_bg'],
        'raw_energy': s['energy'],
        'raw_energy_bg': s['energy_bg'],
        'cost': cost,
        'icon': s['icon'],
        'effect_html': s['desc_html'],
        'effect_text': s['desc_text'],
        'term_refs': s['term_refs'],
    }
    if s.get('placeholder_name'):
        sk['_placeholder_name'] = True
    if energy_req:
        sk['energy_req'] = energy_req
    return sk


def build_summon(s: dict) -> dict:
    """召唤物无 cost(玩家不出召唤物本身,只是技能/卡牌的产物);raw life/energy 仍记录。"""
    out = {
        'name': s['name'],
        'type': '召唤物',
        'icon': s['icon'],
        'raw_life': s['life'],
        'raw_energy': s['energy'],
        'effect_html': s['desc_html'],
        'effect_text': s['desc_text'],
        'term_refs': s['term_refs'],
    }
    if s.get('placeholder_name'):
        out['_placeholder_name'] = True
    return out


def build_talent(t: dict, entry_cost_hash: str, entry_energy_hash: str) -> dict:
    """天赋牌的 cost 同样从 (life, life_bg, energy, energy_bg) 推。"""
    skill_icon_hash = url_hash(t.get('icon', ''))
    cost, energy_req = cost_from_slots(
        t['life'],
        t['life_bg'],
        t['energy'],
        t['energy_bg'],
        entry_cost_hash=entry_cost_hash,
        entry_energy_hash=entry_energy_hash,
        skill_icon_hash=skill_icon_hash,
    )
    text = html_to_multiline_text(t['desc_html'])
    out = {
        'name': t['name'],
        'type': '装备牌',
        'raw_life': t['life'],
        'raw_life_bg': t['life_bg'],
        'raw_energy': t['energy'],
        'raw_energy_bg': t['energy_bg'],
        'cost': cost,
        'icon': t['icon'],
        'effect_html': t['desc_html'],
        'effect_text': text,
        'term_refs': t['term_refs'],
    }
    if energy_req:
        out['energy_req'] = energy_req
    sub = extract_battle_action(t['desc_html'])
    if sub:
        out['sub_type'] = sub
    dc = extract_deck_constraint(text)
    if dc:
        out['deck_constraint'] = dc
    return out
