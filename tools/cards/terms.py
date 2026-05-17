"""术语提取 — 从 wiki HTML 的 ``<u>surface</u>`` + ``<span data-type="详情" data-name=...>`` 配对抽 term 字典。

从 parse.py 拆出。term 处理涉及 layout A1/A2/B 多种 wiki schema 容错 +
_KNOWN_TERMS 跨卡 term 表(cli pre-scan 后 populate)。
"""

from __future__ import annotations

import html
import re

from tools.cards.html_utils import _next_after_u, _parse_fragment, strip_html
from tools.cards.overrides import (
    KNOWN_LAYOUT_B_SURFACES as _KNOWN_LAYOUT_B_SURFACES,
    KNOWN_LONG_SURFACES as _KNOWN_LONG_SURFACES,
    TERM_SURFACE_REPLACEMENTS as _TERM_SURFACE_REPLACEMENTS,
)
from tools.cards.constants import SURFACE_NAME_MAX_LEN as _SURFACE_NAME_MAX_LEN

# 全局 term 表(cli pre-scan 后 populate;extract_terms 用作 layout A2 豁免源)
_KNOWN_TERMS: set[str] = set()


def set_known_terms(known: set[str]) -> None:
    """设置全局 term 表(cli pre-scan 后调)。允许 surface 在表内的 explanation 缺 ':' 形式。"""
    global _KNOWN_TERMS
    _KNOWN_TERMS = set(known)


def _collect_term_pairs(html_str: str) -> tuple[list[tuple[str, str]], list[str]]:
    """用 lxml tree 收集 (surface, data-name) 配对 + 所有 detail-span 的 data-name 序列。

    配对规则:每个 ``<u>X</u>`` 后紧跟(中间仅 close tags)的 ``<span data-type="详情" data-name="Y">``
    被视为一对 (X, Y)。HTML 能读取到的所有嵌套术语都包含。
    """
    tree = _parse_fragment(html_str)
    if tree is None:
        return [], []
    refs = [s.get('data-name', '') for s in tree.iter('span') if s.get('data-type') == '详情']
    pairs: list[tuple[str, str]] = []
    for u in tree.iter('u'):
        nxt = _next_after_u(u)
        if nxt is None:
            continue
        if nxt.tag != 'span' or nxt.get('data-type') != '详情':
            continue
        surface = ''.join(u.itertext()).strip().rstrip('：:').strip()
        data_name = nxt.get('data-name', '')
        if not surface or not data_name:
            continue
        pairs.append((surface, data_name))
    return pairs, refs


def collect_layout_a_terms(html_str: str) -> set[str]:
    """从 html 收集所有 layout A1 surface(explanation 严格 startswith surface + ':')。

    cli pre-scan 用此函数 build cross-card term 表(B 类豁免源)。
    """
    out = set()
    pairs, _ = _collect_term_pairs(html_str)
    for raw_surface, raw_dataname in pairs:
        if not raw_surface:
            continue
        surface = _TERM_SURFACE_REPLACEMENTS.get(raw_surface, raw_surface)
        inner_html = html.unescape(raw_dataname)
        explanation = strip_html(inner_html).strip()
        for sep in ('：', ':'):
            if explanation.startswith(surface + sep):
                out.add(surface)
                break
    return out


def extract_terms(html_str: str) -> dict[str, str]:
    """从 ``<span data-type="详情">`` 提取所有 ``data-name`` 内嵌术语。

    用 lxml tree 配对 ``<u>surface</u>`` 与紧跟的 ``data-name=tooltip``;
    surface 是 wiki 干净文本,作为 canonical name(inner data-name 偶尔重字 / 笔误)。

    data-name 双重 escape:``&lt;`` → ``<`` (HTML 实体) → strip tag → 文本。
    """
    out: dict[str, str] = {}
    pairs, _ = _collect_term_pairs(html_str)
    for raw_surface, raw_dataname in pairs:
        if not raw_surface:
            continue
        # C 类 wiki typo:用 user 判定的"真值"替换 raw surface
        surface = _TERM_SURFACE_REPLACEMENTS.get(raw_surface, raw_surface)
        if len(surface) > _SURFACE_NAME_MAX_LEN and surface not in _KNOWN_LONG_SURFACES:
            raise ValueError(
                f'extract_terms: surface name 超长 (len={len(surface)} > {_SURFACE_NAME_MAX_LEN}): '
                f'{surface!r};若是合法 wiki term,加入 _KNOWN_LONG_SURFACES 白名单(见 parse.py)'
            )
        inner_html = html.unescape(raw_dataname)
        explanation = strip_html(inner_html).strip()
        # layout 检查:
        # A1 严格:explanation startswith surface + ':' (strip 前缀)
        # A2 缺':':explanation startswith surface,但 surface 在跨卡 term 表(已被其他卡 layout A 声明)→ 豁免
        # B:不命中 A1/A2,需要 KNOWN_LAYOUT_B_SURFACES 白名单
        layout_a_match = False
        for sep in ('：', ':'):
            if explanation.startswith(surface + sep):
                explanation = explanation[len(surface) + len(sep) :].strip()
                layout_a_match = True
                break
        if not layout_a_match and explanation.startswith(surface) and surface in _KNOWN_TERMS:
            # B 类:缺 ':' 分隔符,但 surface 已在跨卡 term 表 → 豁免
            explanation = explanation[len(surface) :].strip()
            layout_a_match = True
        if not layout_a_match and surface not in _KNOWN_LAYOUT_B_SURFACES:
            raise ValueError(
                f'extract_terms: surface={surface!r} 的 explanation 不以 "<surface>:" 开头 (layout B);'
                f' explanation[:80]={explanation[:80]!r};若是合法 wiki layout,加入 overrides.KNOWN_LAYOUT_B_SURFACES'
            )
        prev = out.get(surface)
        if prev is None or len(explanation) > len(prev):
            out[surface] = explanation
    return out


def find_term_refs(html_str: str) -> list[str]:
    """提取 ``data-name`` 中的 surface name 列表(去重保序)。

    surface name 从 data-name 内嵌 HTML 的开头 ``<前缀>:`` 提取。
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    _, refs = _collect_term_pairs(html_str)
    for raw_dataname in refs:
        inner = html.unescape(raw_dataname)
        text = strip_html(inner)
        m = re.match(r'^([^:：]+)[:：]', text)
        if not m:
            continue
        name = m.group(1).strip()
        if name not in seen_set:
            seen.append(name)
            seen_set.add(name)
    return seen
