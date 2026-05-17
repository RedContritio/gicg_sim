"""字段 extractors — 从 effect_html / effect_text / attr 提取 schema 字段。

无通配符贪心,全用 string slicing 或精确边界 character class。
所有 yaml 数据 / 白名单 / phrase 常量从 ``tools.cards.constants`` import。

cost slot resolution 拆出至 cost_resolve.py。本文件留 effect-text-level extract +
URL/hash regex 工具。
"""

from __future__ import annotations

import re

from tools.cards.constants import (
    BATTLE_ACTION_PHRASES,
    DURATION_PATTERNS,
    GENERATED_BY_PHRASES,
    WEAPON_TYPES,
)

# Cost icon URL 提取(action / talent 卡 raw_text 内嵌的 costBgIcon / energyBgIcon URL)
_COST_ICON_RE = re.compile(
    r'"costBgIcon"\s*:\s*\{[^}]*?"list"\s*:\s*\[\s*"(https://[^"]+)"',
    re.DOTALL,
)
_ENERGY_ICON_RE = re.compile(
    r'"energyBgIcon"\s*:\s*\{[^}]*?"list"\s*:\s*\[\s*"(https://[^"]+)"',
    re.DOTALL,
)
_HASH_RE = re.compile(r'/([0-9a-f]{32})_\d+\.png$')

# 句首 prefix:文本开头或常见分隔符
_SENTENCE_PREFIX_RE = r'(?:^|[\n。；;,，:：])\s*'


def extract_battle_action(html_str: str) -> str:
    """从 effect_html 提取 '战斗行动' / '快速行动' 标签。

    源(优先级):
    1. HTML 明确 markup `<strong><u>X</u>` → markup 命中即返回
    2. text 句首 phrase(用 strip_html 严格 lxml 解析,不用 regex strip)

    严格契约:markup 命中 + text 命中不同 phrase → raise(数据冲突)。
    """
    from tools.cards.html_utils import strip_html

    markup_hit = ''
    for action in BATTLE_ACTION_PHRASES:
        if f'<strong><u>{action}</u>' in html_str:
            markup_hit = action
            break
    text_only = strip_html(html_str)
    text_hit = ''
    for action in BATTLE_ACTION_PHRASES:
        if re.search(_SENTENCE_PREFIX_RE + action + '：', text_only):
            text_hit = action
            break
    if markup_hit and text_hit and markup_hit != text_hit:
        raise ValueError(f'extract_battle_action: markup 命中 {markup_hit!r} vs text 命中 {text_hit!r} 不一致')
    return markup_hit or text_hit


def extract_deck_constraint(text: str) -> str:
    """从 effect_text 提取 '（...才能加入牌组）' 这类 constraint。

    严格白名单:仅接受括号内含 '才能加入牌组' 的子串(wiki 实际数据全部 deck constraint 都用此 phrase)。
    旧版 `'至少' in s and '角色' in s` substring AND 误匹配('至少 X 张牌时为该角色生成' 等)已删,
    因为合法 deck constraint 中 '至少角色' phrase 必伴 '才能加入牌组'(冗余检查)。
    """
    for open_ch, close_ch in [('（', '）'), ('(', ')')]:
        start = 0
        while True:
            i = text.find(open_ch, start)
            if i < 0:
                break
            j = text.find(close_ch, i + 1)
            if j < 0:
                break
            inner = text[i + 1 : j]
            if '才能加入牌组' in inner:
                return inner
            start = j + 1
    return ''


def extract_duration(text: str) -> str:
    """从 effect_text 严格匹配 duration phrase。

    严格白名单:仅接受 '可用次数: N' / '持续回合: N' / 句首 '本回合'。
    其他 'X 持续' 等模糊 substring 不再误匹配(空字符串)。
    """
    for pat, fmt in DURATION_PATTERNS:
        m = pat.search(text)
        if m:
            return fmt.format(*m.groups()) if m.groups() else fmt
    return ''


def extract_weapon_type(text: str) -> str:
    """从 effect_text 匹配 'X角色' / '「X」角色' (反向 enum 严格 phrase)。

    严格契约:无通配符 regex,只接受 weapon enum × {裸,「」} 两种 exact phrase。
    未匹配返回空(不 raise — 调用方按 tag gate 判)。
    """
    for w in WEAPON_TYPES:
        if f'{w}角色' in text or f'「{w}」角色' in text:
            return w
    return ''


def extract_generated_by(acquire_a: str) -> str:
    """从 attr['获取'] 字符串严格判定是否为"效果生成 / 效果获得"标记。

    严格 suffix 白名单:acquire 是单短语字段(如 'X效果生成' / 'X技能效果生成');
    phrase 必须在末尾;phrase 出现但不在末尾 → raise(可疑 wiki 数据)。
    """
    if not acquire_a:
        return ''
    for phrase in GENERATED_BY_PHRASES:
        if acquire_a.endswith(phrase):
            return acquire_a
        if phrase in acquire_a:
            raise ValueError(f'extract_generated_by: acquire 含 {phrase!r} 但不在末尾:{acquire_a!r}')
    return ''


def extract_for_character(text: str) -> str:
    """从 effect_text 反向匹配 character 名(从 list API 取 enum,长度倒序优先长名)。

    替代旧版"我方出战角色为...时"单 anchor:严格 enum 匹配;不在 character 库中的名不会被误匹配。
    """
    from tools.cards.constants import load_character_names

    names = load_character_names()
    for name in names:
        if name in text:
            return name
    return ''


def extract_cost_icon_url(raw_text: str) -> str:
    """从 entry_page raw_text 抓 ``costBgIcon`` 第一张 URL。"""
    text2 = raw_text.replace('\\"', '"')
    m = _COST_ICON_RE.search(text2)
    return m.group(1) if m else ''


def extract_energy_icon_url(raw_text: str) -> str:
    """从 entry_page raw_text 抓 ``energyBgIcon`` 第一张 URL。空字符串表示无第二维 cost icon。"""
    text2 = raw_text.replace('\\"', '"')
    m = _ENERGY_ICON_RE.search(text2)
    return m.group(1) if m else ''


def url_hash(url: str) -> str:
    m = _HASH_RE.search(url)
    return m.group(1) if m else ''
