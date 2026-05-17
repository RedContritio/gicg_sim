"""tools.cards 静态常量 + wiki schema-based loader。

仅放"wiki schema 内置 / 算法 const / 一次性 user 标定后稳定的基础数据"。
不放 wiki bug 修复(cost overrides / skill name overrides / surface 白名单),
后者在 ``tools.cards.overrides``。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

# === 路径常量 ===
COST_BG_MAPPING_PATH = Path('data/cards/cost_bg_mapping.yaml')
ATTR_VALUE_SCHEMA_PATH = Path('data/cards/attr_value_schema.yaml')
ELEMENTS_PATH = Path('data/cards/elements.yaml')
JUDGEMENT_PATH = Path('data/cost_icons/_judgement.yaml')
INDEX_PATH = Path('data/cost_icons/_index.yaml')
RAW_LIST_DIR = Path('data/raw_list')


# === wiki phrase / enum 常量(wiki 数据本身用) ===

# wiki HTML 中标 '战斗行动' / '快速行动' 的 phrase
BATTLE_ACTION_PHRASES: tuple[str, ...] = ('战斗行动', '快速行动')

# wiki action 卡 weapon_type 字面 enum
WEAPON_TYPES: tuple[str, ...] = ('双手剑', '单手剑', '长柄武器', '弓', '法器', '其他武器')

# attr['获取'] suffix 标识"X效果生成 / X效果获得"为 generated_by
GENERATED_BY_PHRASES: tuple[str, ...] = ('效果生成', '效果获得')

# acquire attr key 双名(action='获取', character='获取方式')
ACQUIRE_KEYS: tuple[str, ...] = ('获取', '获取方式')

# wiki skill 空模板 desc 字面(name 空 / 默认标题 时若 desc 是这些则视为空模板 skip)
SKILL_PLACEHOLDER_DESC: tuple[str, ...] = (
    '',
    '<p></p>',
    '<p></p><p></p>',
    '<p><br></p>',
    '<p><br/></p>',
)

# action duration phrase 严格白名单
DURATION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'可用次数\s*[:：]\s*(\d+)'), '可用次数{}'),
    (re.compile(r'持续回合\s*[:：]\s*(\d+)'), '持续{}回合'),
    (re.compile(r'(?:^|[\n。；;,，])\s*本回合'), '持续本回合'),
]

# _judgement.yaml 字面 → cost dict 的 kind
JUDGE_KIND_TO_COST_KIND: dict[str, str] = {
    '同色': '同色',
    '无色': '无色',
    '任意': '无色',
    '风': '风',
    '火': '火',
    '雷': '雷',
    '冰': '冰',
    '水': '水',
    '草': '草',
    '岩': '岩',
}


# === 算法阈值 ===

# term surface name 长度上限(超长非白名单 raise;白名单见 overrides.KNOWN_LONG_SURFACES)
SURFACE_NAME_MAX_LEN = 12


# === yaml output schema 中英 key 映射(C-9 全中文化) ===
# parser 内部代码用英文 key 减少冲突;transform 出口一次性 translate_keys 输出中文。
# 仅顶层 schema key 翻译;'始基力' / 'attr' 内的中文子 key('元素'/'武器' 等) 已是中文不动。
# 技术保留英文 key:id / _raw_path / _placeholder_name(系统标记)
EN_TO_ZH_KEYS: dict[str, str] = {
    # 顶层基础
    'name': '名称',
    'title': '标题',
    'parent_class': '父类',
    'desc': '描述',
    'icon_url': '图标URL',
    'header_img_url': '头图URL',
    'version': '版本',
    'attr': '属性',
    'flavor_html': '故事HTML',
    'flavor_text': '故事文本',
    'terms': '术语',
    # character base
    'element': '元素',
    'weapon': '武器',
    'faction': '阵营',
    'hp': '生命值',
    'energy': '能量上限',
    'acquire': '获得方式',
    'common_img': '普通图',
    'gold_img': '金图',
    'raw_life_bg': '原始life_bg',
    'raw_energy_bg': '原始energy_bg',
    'cost_bg_icon_url': '花费图标URL',
    'skills': '技能',
    'summons': '召唤物',
    'talent': '天赋牌',
    'jiqiao': '自行巧局',
    'variants': '变体',
    # skill / summon / talent
    'type': '类型',
    'raw_life': '原始life',
    'raw_energy': '原始energy',
    'cost': '花费',
    'energy_req': '能量需求',
    'icon': '图标',
    'effect_html': '效果HTML',
    'effect_text': '效果文本',
    'term_refs': '术语引用',
    'sub_type': '子类型',
    'deck_constraint': '套牌约束',
    # action 卡专属
    'sub_class': '子类',
    'tags': '标签',
    'cost_text': '花费文本',
    'duration': '持续时间',
    'weapon_type': '武器类型',
    'requires_char': '角色限定',
    'is_combat_action': '战斗行动',
    'generated_by': '生成来源',
    # variant 内部 (复用 character base / skill keys)
    'mode': '模式',
}


def translate_keys(obj):
    """深度递归把 dict / list 中的英文 schema key 翻译成中文。

    技术 key(以 _ 开头 / 已是中文) / 不在 EN_TO_ZH_KEYS 表中的 key 保留原样。
    """
    if isinstance(obj, dict):
        return {EN_TO_ZH_KEYS.get(k, k): translate_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [translate_keys(x) for x in obj]
    return obj


# === wiki schema-based loader (一次性 user 标定后稳定) ===


def load_cost_bg_mapping() -> dict[int, str | None]:
    """data/cards/cost_bg_mapping.yaml → bg 编号 → kind 统一映射。"""
    doc = yaml.safe_load(COST_BG_MAPPING_PATH.read_text(encoding='utf-8'))
    return dict(doc['bg_kind'])


def load_judgement() -> dict[str, tuple[str, int]]:
    """_judgement.yaml + _index.yaml → hash → (cost_kind, n)。"""
    judge_doc = yaml.safe_load(JUDGEMENT_PATH.read_text(encoding='utf-8'))
    index_doc = yaml.safe_load(INDEX_PATH.read_text(encoding='utf-8'))
    out: dict[str, tuple[str, int]] = {}
    for nn, raw in (judge_doc.get('judgements', {}) or {}).items():
        if raw is None:
            continue
        nn_s = f'{int(nn):02d}' if isinstance(nn, int) else str(nn).strip()
        s = str(raw).strip()
        m = re.match(r'^([\u4e00-\u9fff]+?)\s*[:：]?\s*(\d+)$', s)
        if not m:
            continue
        word, n = m.group(1), int(m.group(2))
        kind = JUDGE_KIND_TO_COST_KIND.get(word)
        if kind is None:
            continue
        h = index_doc[nn_s]['hash']
        out[h] = (kind, n)
    return out


def load_attr_value_schema() -> dict[str, str]:
    """data/cards/attr_value_schema.yaml → {attr_key: value_type}。"""
    if not ATTR_VALUE_SCHEMA_PATH.exists():
        return {}
    doc = yaml.safe_load(ATTR_VALUE_SCHEMA_PATH.read_text(encoding='utf-8')) or {}
    return dict(doc.get('attr_value_schema') or {})


def load_elements() -> dict[str, str]:
    """data/cards/elements.yaml → {wiki 字面: 单字元素名}。"""
    return dict(yaml.safe_load(ELEMENTS_PATH.read_text(encoding='utf-8'))['elements'])


def load_character_names() -> list[str]:
    """data/raw_list/character.json → 角色名 enum,按长度倒序(优先匹配长名)。"""
    fp = RAW_LIST_DIR / 'character.json'
    if not fp.exists():
        raise FileNotFoundError(f'缺 {fp};请先跑 fetch_list')
    items = json.loads(fp.read_text(encoding='utf-8'))
    return sorted({it.get('title', '') for it in items if it.get('title')}, key=lambda x: -len(x))


# === helper ===


def get_acquire(attr_dict: dict) -> str:
    """从 attr 读取"获得途径"(两 key 都尝试,同 attr 同时含两 key 且值不同 raise)。"""
    vals: list[tuple[str, str]] = []
    for k in ACQUIRE_KEYS:
        v = (attr_dict.get(k) or [''])[0]
        if v:
            vals.append((k, v))
    if len(vals) >= 2:
        unique = {v for _, v in vals}
        if len(unique) > 1:
            raise ValueError(f'attr 同时含 {ACQUIRE_KEYS} 且值不同:{vals}')
    return vals[0][1] if vals else ''
