"""raw JSON 公共解析层 — module 解码 / attr 校验 / skill items。

HTML / 术语相关已拆出至 html_utils.py 与 terms.py。本文件留 module-level 与
attr-level 处理 + skill items 规范化。
"""

from __future__ import annotations

import json
import re

PARENT_CLASS = {
    '角色牌': 'character',
    '行动牌': 'action',
    '魔物牌': 'monster',
}

from tools.cards.constants import (
    SKILL_PLACEHOLDER_DESC as _SKILL_PLACEHOLDER_DESC,
    load_attr_value_schema,
)
from tools.cards.html_utils import strip_html
from tools.cards.overrides import load_skill_name_overrides
from tools.cards.terms import find_term_refs


def consume_module(module: dict, tracker, base: str) -> tuple[str, list[dict]]:
    """读 module name + 解析每个 component 的 JSON-encoded data。

    把 module name + components.data 标 visited(string-level 消化)。
    严格契约:JSON 解析失败 raise(wiki 数据损坏不应静默丢失整 component)。
    """
    tracker.visit(f'{base}.name')
    name = module.get('name', '')
    decoded: list[dict] = []
    for comp in module.get('components', []) or []:
        raw_data = comp.get('data', '')
        if not raw_data:
            tracker.visit(f'{base}.components[*].data')
            continue
        try:
            decoded.append(json.loads(raw_data))
        except json.JSONDecodeError as e:
            raise ValueError(
                f'consume_module: {base}.components[*].data JSONDecodeError (module={name!r}): {raw_data[:200]!r}'
            ) from e
        tracker.visit(f'{base}.components[*].data')
    return name, decoded


_PURE_HAN_RE = re.compile(r'^[一-鿿]+$')
_INT_RE = re.compile(r'^\d+$')
_INT_WITH_UNIT_RE = re.compile(r'^\d+(?:点(?:战意)?)?$')
# cost_phrase: 数字 / N点充能 / N<元素>元素 / N点 / N，M点充能 等
_COST_PHRASE_RE = re.compile(r'^\d+(?:点充能|点|[一-鿿]元素)?(?:[，,]\d+点(?:充能)?)?$')
_PURE_HAN_OPT_PUNCT_RE = re.compile(r'^[一-鿿]+(?:[·，/][一-鿿]+)*$')
_HAS_HAN_RE = re.compile(r'[一-鿿]')


def _check_attr_value(value_type: str, sub: str) -> bool:
    """根据 value_type 校验子串。返回 True 如果合规。"""
    if value_type == 'pure_han':
        return bool(_PURE_HAN_RE.match(sub))
    if value_type == 'int':
        return bool(_INT_RE.match(sub))
    if value_type == 'int_with_unit':
        return bool(_INT_WITH_UNIT_RE.match(sub))
    if value_type == 'cost_phrase':
        return bool(_COST_PHRASE_RE.match(sub))
    if value_type == 'element_token':
        from tools.cards.constants import load_elements

        return sub in load_elements()
    if value_type == 'pure_han_optional_punct':
        return bool(_PURE_HAN_OPT_PUNCT_RE.match(sub))
    if value_type == 'free_text_with_han':
        return bool(_HAS_HAN_RE.search(sub))
    raise ValueError(f'attr_value_schema 未知 value_type {value_type!r}')


def parse_attr(attr_list: list[dict], tracker, base_path: str) -> dict[str, list[str]]:
    """attr [{key, value}] → dict,自动拆分 ;/；/,;前导冒号 strip。

    P-8 加严:按 attr_value_schema.yaml 声明的 value_type 校验子串。
    schema 未声明的 key warn;子串不合规 warn(指明 expected pattern)。
    """
    import warnings as _w

    schema = load_attr_value_schema()
    out: dict[str, list[str]] = {}
    for kv in attr_list:
        tracker.visit(f'{base_path}[*].key')
        tracker.visit(f'{base_path}[*].value')
        key = kv.get('key', '').rstrip('：:').strip()
        if not key:
            continue
        value_type = schema.get(key)
        if value_type is None:
            _w.warn(f'parse_attr: 未声明 attr_value_schema 的 key {key!r}', stacklevel=3)
        vals: list[str] = []
        for v in kv.get('value', []):
            v = v.lstrip('：:').strip()
            for sub in re.split(r'[；;,]', v):
                sub = sub.strip()
                if not sub:
                    continue
                if value_type and not _check_attr_value(value_type, sub):
                    _w.warn(
                        f'parse_attr: key={key!r} 子串 {sub!r} 不符合 expected {value_type!r}',
                        stacklevel=3,
                    )
                vals.append(sub)
        out[key] = vals
    return out


def parse_skill_items(items: list[dict], card_id: int = 0, module_kind: str = '') -> list[dict]:
    """规范化 卡牌技能 / 召唤物 / 天赋牌 list[]。跳过空白模板。

    严格契约:name 为空 / '默认标题' 时,desc 必须满足下列之一:
    1. 在 placeholder 白名单内 → skip
    2. 在 skill_name_overrides.yaml 命中 (action=rename) → 用 override name
    3. 在 skill_name_overrides.yaml 命中 (action=warn) → warn + 保留 '默认标题'
    4. 否则 raise
    """
    import hashlib
    import warnings as _w

    overrides = load_skill_name_overrides() if card_id and module_kind else {}
    out = []
    for it in items:
        name = it.get('tab_name', '').strip()
        placeholder_name = False
        desc_html = ''
        desc_obj = it.get('desc', {})
        if isinstance(desc_obj, dict):
            values = desc_obj.get('value', [])
            if values:
                desc_html = values[0] or ''
        if not name or name == '默认标题':
            stripped = desc_html.strip()
            if stripped in _SKILL_PLACEHOLDER_DESC:
                continue
            # 查 override
            desc_md5 = hashlib.md5(desc_html.encode('utf-8')).hexdigest()
            ovr = overrides.get((card_id, module_kind, desc_md5))
            if ovr:
                act = ovr.get('action')
                if act == 'rename':
                    name = ovr['name']
                elif act == 'warn':
                    _w.warn(
                        f"parse_skill_items: card_id={card_id} {module_kind} 接受 placeholder name='默认标题' "
                        f'(override action=warn): {ovr.get("why", "")}',
                        stacklevel=2,
                    )
                    placeholder_name = True
                else:
                    raise ValueError(f'skill_name_overrides.yaml: 未知 action {act!r}')
            else:
                raise ValueError(
                    f'parse_skill_items: card_id={card_id} {module_kind} name={name!r} 但 desc 非 placeholder\n'
                    f'  desc_md5={desc_md5}\n'
                    f'  desc_html[:200]={desc_html[:200]!r}\n'
                    f'  desc_text[:120]={stripped[:120]!r}\n'
                    f'  → 请在 data/cards/skill_name_overrides.yaml 加 override(完整 desc_html 写 yaml signature)'
                )
        out.append(
            {
                'name': name,
                'placeholder_name': placeholder_name,
                'skill_type': it.get('skill_type', '').strip(),
                'life': it.get('life', 0),
                'life_bg': it.get('life_bg', 0),
                'energy': it.get('energy', 0),
                'energy_bg': it.get('energy_bg', 0),
                'icon': it.get('icon', ''),
                'desc_html': desc_html,
                'desc_text': strip_html(desc_html),
                'term_refs': find_term_refs(desc_html),
                'tab_id': it.get('tab_id', ''),
            }
        )
    return out
