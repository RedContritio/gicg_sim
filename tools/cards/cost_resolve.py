"""Cost slot resolution — raw (life, life_bg, energy, energy_bg) → cost dict + energy_req。

从 extractors.py 拆出。多源严格交叉验证(主 bg_kind / hash judgement / list filter /
attr 花费 / skill 模板),任一不一致 raise(无 fallback、无源接管)。
"""

from __future__ import annotations

import re

from tools.cards.constants import (
    load_cost_bg_mapping,
    load_judgement,
)
from tools.cards.overrides import load_cost_overrides

_NUM_RE = re.compile(r'(\d+)')


def _resolve_slot(
    n: int,
    bg: int,
    entry_hash: str,
    list_hash: str,
    bg_kind: dict[int, str | None],
    judgements: dict[str, tuple[str, int]],
    slot_label: str,
) -> tuple[str | None, int]:
    """单个 slot 多源严格解析 → (kind, count)。

    源 P:bg → kind via bg_kind mapping(必须命中)
    源 S1:entry_hash → (kind, n) via _judgement.yaml(entry_page 内嵌)
    源 S2:list_hash → (kind, n) via _judgement.yaml(list API ext)

    严格契约(无 fallback、无源接管):
    - entry_hash / list_hash 都有 → 必须相等(URL 同源)
    - 主源 mapping 未知 bg → raise
    - 任一备源出 kind 与主源不一致 → raise
    - character skill 无 hash 时:接受单源主源
    """
    if entry_hash and list_hash and entry_hash != list_hash:
        raise ValueError(f'{slot_label}: entry_page hash={entry_hash} vs list API hash={list_hash} 不一致(应同 URL)')
    h = entry_hash or list_hash
    if bg not in bg_kind:
        sec = judgements.get(h) if h else None
        sec_str = f'备源 hash={h}→{sec}' if sec else f'备源缺(hash={h!r})'
        raise ValueError(f'{slot_label}: 主源未知 bg={bg}(n={n});{sec_str};请在 cost_bg_mapping.yaml 补充该 bg 编号')
    primary_kind = bg_kind[bg]
    secondary: tuple[str, int] | None = judgements.get(h) if h else None

    if primary_kind is None:
        if n != 0 and bg != 13:
            raise ValueError(f'{slot_label}: bg={bg}(空槽位)但 n={n} 非 0')
        if secondary is not None and secondary[1] != 0:
            raise ValueError(f'{slot_label}: 主源 bg={bg} 空,但备源 hash={h}→{secondary} 非空,数据冲突')
        return None, 0

    if secondary is not None and secondary != ('能量需求', n):
        sec_kind, sec_n = secondary
        if sec_kind != primary_kind or sec_n != n:
            raise ValueError(f'{slot_label}: 主源 (bg={bg}→{primary_kind}, n={n}) vs 备源 hash={h}→{secondary} 不一致')
    return primary_kind, n


# Skill cost 模板(基于 skill_type + character element 推 expected cost / energy_req)。
# 模板规则源自七圣召唤标准设计:普攻/战技/爆发都有固定 cost 模式。
# 模板作为独立信源参与 cost 交叉验证;模板与其他源不一致 → raise 由 user 显式 override。
def skill_cost_template(
    skill_type: str, element: str, raw_life: int, raw_energy: int
) -> tuple[dict[str, int] | None, int]:
    """根据 skill_type + character element 推 (expected_cost, expected_energy_req)。

    返回 (None, 0) 表示无模板预期(skill_type 不在模板覆盖范围,跳过模板源验证)。

    模板规则(七圣召唤标准):
    - 普通攻击: cost = {<element>: 1, '无色': 2}, energy_req=0
    - 元素战技: cost = {<element>: 3}, energy_req=0
    - 元素爆发: cost = {<element>: raw_life}(主元素 cost 数量从 raw 读), energy_req=raw_energy
    - 被动技能: cost = {}, energy_req=0
    - 其他: 无模板(返回 None)
    """
    if not element:
        return None, 0
    if skill_type == '普通攻击':
        return {element: 1, '无色': 2}, 0
    if skill_type == '元素战技':
        return {element: 3}, 0
    if skill_type == '元素爆发':
        return {element: raw_life}, raw_energy
    if skill_type == '被动技能':
        return {}, 0
    return None, 0


def cost_from_slots(
    life: int,
    life_bg: int,
    energy: int,
    energy_bg: int,
    entry_cost_hash: str = '',
    entry_energy_hash: str = '',
    skill_icon_hash: str = '',
    list_cost_hash: str = '',
    list_energy_hash: str = '',
    list_filter_花费: int | None = None,
    attr_花费_total: int | None = None,
    skill_type: str = '',
    character_element: str = '',
) -> tuple[dict[str, int], int]:
    """从 raw 的 cost slot 推 cost dict + 能量消耗(全源严格交叉验证 + override)。

    schema:
    - slot1 = (life, life_bg), slot2 = (energy, energy_bg)
    - 两个 slot 共享同一 bg 编号空间;bg=8 表示能量需求(进 energy_req)
    - 同 kind 出现两次时累加 count

    数据源(每源都参与交叉验证,任一不一致 raise — 不存在源接管):
    - 主:bg_kind mapping(必有)
    - entry_cost_hash / entry_energy_hash:entry_page raw 内嵌 cost icon URL → hash
    - list_cost_hash / list_energy_hash:list API ext.costBgIcon/energyBgIcon → hash
    - list_filter_花费:list API filter.text 中 "花费/花费N" 的 N(总数信号)
    - attr_花费_total:entry_page attr['花费'] 数字(总数信号)
    - skill_type + character_element:character skill 模板源(普攻/战技/爆发的标准 cost)

    严格契约(B + E):
    1. 先查 cost_overrides.yaml:完整签名 exact match → 直接用 override(无 fallback)
    2. 否则全源交叉验证;任一不一致 raise

    Caller 契约:
    - action / talent 卡:必有 hash 备源(entry_cost_hash + list_cost_hash 等)
    - character standard skill:无 hash 但有 skill_type + character_element 模板源
    - character variant skill / monster skill:无 hash 也无 template(单源 mapping,wiki schema 事实)

    返回 (cost_dict, energy_req)。
    """
    overrides = load_cost_overrides()
    sig = (
        life,
        life_bg,
        energy,
        energy_bg,
        entry_cost_hash,
        entry_energy_hash,
        skill_icon_hash,
        list_cost_hash,
        list_energy_hash,
        list_filter_花费,
        attr_花费_total,
        skill_type,
        character_element,
    )
    if sig in overrides:
        cost, energy_req = overrides[sig]
        return dict(cost), energy_req

    bg_kind = load_cost_bg_mapping()
    judgements = load_judgement()
    cost: dict[str, int] = {}
    energy_req = 0

    for n, bg, eh, lh, label in [
        (life, life_bg, entry_cost_hash, list_cost_hash, 'slot1(life)'),
        (energy, energy_bg, entry_energy_hash, list_energy_hash, 'slot2(energy)'),
    ]:
        kind, count = _resolve_slot(n, bg, eh, lh, bg_kind, judgements, label)
        if kind is None:
            continue
        if kind == '能量需求':
            energy_req += count
            continue
        cost[kind] = cost.get(kind, 0) + count

    cost_total = sum(cost.values())
    if list_filter_花费 is not None and list_filter_花费 != cost_total:
        raise ValueError(f'list filter 花费={list_filter_花费} vs 推断 cost 总数={cost_total} 不一致;cost={cost}')
    if attr_花费_total is not None and attr_花费_total != cost_total:
        raise ValueError(f"attr['花费']={attr_花费_total} vs 推断 cost 总数={cost_total} 不一致;cost={cost}")

    if skill_type and character_element:
        tpl_cost, tpl_eq = skill_cost_template(skill_type, character_element, life, energy)
        if tpl_cost is not None:
            if tpl_cost != cost or tpl_eq != energy_req:
                raise ValueError(
                    f'skill 模板 (type={skill_type!r}, element={character_element!r}) → '
                    f'expected cost={tpl_cost}, energy_req={tpl_eq};'
                    f'实际推断 cost={cost}, energy_req={energy_req};不一致'
                )

    return cost, energy_req


def parse_energy_from_attr(attr_dict: dict) -> int:
    vals = attr_dict.get('充能') or []
    for v in vals:
        m = _NUM_RE.search(str(v))
        if m:
            return int(m.group(1))
    return 0
