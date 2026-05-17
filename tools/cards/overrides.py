"""tools.cards 中 user 显式判断的 wiki bug 修复 / outlier 处理。

与 ``tools.cards.constants`` 的区别:
- constants 是 wiki schema 内置数据 / 算法常量(parser 永久依赖)
- overrides 是 user review 后入的 wiki typo / 单点豁免(可能随 wiki 修复而失效)

每个 override entry 的"完全相同冲突情况" semantic 由 signature 严格 enforce;
wiki 数据修复 → signature 失效 → parser raise → user 重新 review。
"""

from __future__ import annotations

from pathlib import Path

import yaml

# === 路径(与 constants.py 隔开) ===
COST_OVERRIDES_PATH = Path('data/cards/cost_overrides.yaml')
SKILL_NAME_OVERRIDES_PATH = Path('data/cards/skill_name_overrides.yaml')


# === inline 白名单(条目少 + 静态 set;有 yaml 太重) ===

# term surface name 超长豁免(显式 user review 后接受;新出现长 term 仍触发 raise)
KNOWN_LONG_SURFACES: set[str] = {
    # 七圣召唤位置规则术语(温迪召唤物'暴风之眼' / 500677 无相之冰)
    '距离我方出战角色最近的角色',
    # 砂糖爆发技能名(5361 砂糖天赋牌 / 5507 混元熵增论 引用)
    '禁·风灵作成·柒伍同构贰型',
}


# C-#7 d: extract_terms 期望 layout A (explanation 以 'surface:' 开头);
# layout B (无 surface 前缀) 视为 wiki 异常 raise,显式列入白名单豁免。
# C 类 wiki typo 修正:user 显式判定后,把 raw surface 替换成"真值"。
# parser extract_terms 检测到 raw surface 后查此 map,命中则用 corrected surface 作 yaml term key。
# 仅在 raw 与"真值"冲突时使用(C 类 wiki 字符 typo);其他类型(layout B / 缺':')不需要替换。
TERM_SURFACE_REPLACEMENTS: dict[str, str] = {
    # C2: 白术 talent — explanation 用 '郤',user 选解释段中的字
    '无卻气护盾': '无郤气护盾',
    # C6: 歼灭机关·荒 — explanation 用 '机关·区域警戒型·荒',user 说'生成'是描述应在外面
    '生成机关·区域警戒型·荒': '机关·区域警戒型·荒',
    # D1: 船坞长剑 — '团结' 是卡机制不是 term;wiki 链给的是 '舍弃' 术语解释
    '「团结」': '舍弃',
    # D2/D3/D4: 引号差异,无引号是标准 term name
    '「快速行动」': '快速行动',
    '「战斗行动」': '战斗行动',
    '「美露莘的声援」': '美露莘的声援',
}


KNOWN_LAYOUT_B_SURFACES: set[str] = {
    # === A 类:真 layout B(wiki 设计 explanation 完全不重复 surface,直接说明 effect)===
    '万能元素',  # 5448 派蒙等:explanation '可以视为任何类型的元素...' 直接定义
    '下落攻击',  # 500041:explanation '角色被切换为「出战角色」后...' 直接说明
    '战斗行动',  # 部分卡(凯瑟琳/神性之陨)layout B:explanation '我方执行了一次...' 无前缀
    '快速行动',  # 部分卡 layout B
    'Upa Shato',  # 5380 重铸·岩盔:explanation '造成5点物理伤害。' 直接 effect
    '不稳定孢子云',  # 5379:explanation '造成3点草元素伤害。' 直接 effect
    '冰潮的涡旋',  # 6171:explanation '造成2点冰元素伤害...' 直接 effect
    '凝浪之光剑',  # 6171:explanation '造成2点冰元素伤害,召唤光降之剑。' 直接 effect
    '孤风刀势',  # 5381:explanation '召唤剑影·孤风。' 直接 effect
    '霜驰影突',  # 5381:explanation '造成1点冰元素伤害...' 直接 effect
    '踏潮',  # 5886 北斗:explanation '元素战技:(需准备1个行动轮)...' 直接 effect
    # === C 类:wiki 字符 typo,user 选用 surface(explanation 错字)===
    '卡萨扎莱宫的无微不至',  # 500294 多莉:explanation 缺首字 '卡' (user: 用 surface)
    '雾虚之召',  # 500994 雷萤术士:'召' vs '兆' (user: 用 surface)
    '风元素伤害',  # 500192 流浪者:某处 explanation 多余'风' (user: 移除多余字)
    '禁·风灵作成·柒伍同构贰型',  # 5361 砂糖 / 5507:'柒' vs '染' (user: 用 surface)
    # === B 类(缺 ':' 分隔符):大多由 cross-card term 表 _KNOWN_TERMS 自动 cover ===
    # 但下列 surface 全集都是 layout B 形式(从未被 layout A 声明),term 表不 cover,需白名单:
    '充能',  # 5448 派蒙 / 5458 田铁嘴 等:explanation '角色使用...时,需要消耗充能...' 无前缀
    '可用次数',  # 8 张支援卡:explanation '此牌效果触发后,会消耗1次可用次数...' 无前缀
    '厄灵·草之灵蛇',  # 502899 / 502911:explanation '厄灵·草之灵蛇装备牌费用:0...' 缺 ':'(全集 layout B)
    '火元素相关反应',  # 5390 元素共鸣 火:全集 layout B,无 layout A 形式
    '燃烧烈焰',  # 5398 元素共鸣 草:全集 layout B
    '激化领域',  # 5398 元素共鸣 草:全集 layout B
    # 已迁 TERM_SURFACE_REPLACEMENTS:
    #   C2 '无卻气护盾' → '无郤气护盾'
    #   C6 '生成机关·区域警戒型·荒' → '机关·区域警戒型·荒'
    #   D1 '「团结」' → '舍弃'
    #   D2/D3/D4 '「快速行动」'/'「战斗行动」'/'「美露莘的声援」' → 无引号版本
}


# === yaml override loader ===


def load_cost_overrides() -> dict[tuple, tuple[dict[str, int], int]]:
    """data/cards/cost_overrides.yaml → 完整签名 → (cost_dict, energy_req)。

    严格契约:每条 override hash 级唯一(by entry_cost_hash + skill_icon_hash 等);重复签名 raise。
    """
    if not COST_OVERRIDES_PATH.exists():
        return {}
    doc = yaml.safe_load(COST_OVERRIDES_PATH.read_text(encoding='utf-8')) or {}
    out: dict[tuple, tuple[dict[str, int], int]] = {}
    for entry in doc.get('overrides') or []:
        sig = entry['signature']
        key = (
            int(sig['life']),
            int(sig['life_bg']),
            int(sig['energy']),
            int(sig['energy_bg']),
            str(sig.get('entry_cost_hash') or ''),
            str(sig.get('entry_energy_hash') or ''),
            str(sig.get('skill_icon_hash') or ''),
            str(sig.get('list_cost_hash') or ''),
            str(sig.get('list_energy_hash') or ''),
            None if sig.get('list_filter_花费') is None else int(sig['list_filter_花费']),
            None if sig.get('attr_花费_total') is None else int(sig['attr_花费_total']),
            str(sig.get('skill_type') or ''),
            str(sig.get('character_element') or ''),
        )
        if key in out:
            raise ValueError(f'cost_overrides.yaml: 重复签名(应 hash 级唯一):{key}')
        cost = dict(entry['result'].get('cost') or {})
        eq = int(entry['result'].get('energy_req') or 0)
        out[key] = (cost, eq)
    return out


def load_skill_name_overrides() -> dict[tuple[int, str, str], dict]:
    """data/cards/skill_name_overrides.yaml → (card_id, module_kind, desc_md5) → entry。"""
    if not SKILL_NAME_OVERRIDES_PATH.exists():
        return {}
    doc = yaml.safe_load(SKILL_NAME_OVERRIDES_PATH.read_text(encoding='utf-8')) or {}
    out: dict[tuple[int, str, str], dict] = {}
    for e in doc.get('overrides') or []:
        key = (int(e['card_id']), str(e['module_kind']), str(e['desc_html_md5']))
        if key in out:
            raise ValueError(f'skill_name_overrides.yaml: 重复签名 {key}')
        out[key] = e
    return out
