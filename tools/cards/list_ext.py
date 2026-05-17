"""加载 + 解析 data/raw_list/<type>.json (list API 批量拉取的 cards channel 信息)。

list API 提供与 entry_page 独立的 cost 信号,用于 transform 阶段交叉验证。
schema: ext.c_<channel_id>.{costBgIcon, energyBgIcon, filter}

filter.text 是 JSON-string 包含 ['类型/支援牌','标签/场地','花费/花费2',...] 等标签;
parse 出 类型 / 标签 / 花费 数字 / 特殊模式 等独立信号。
"""

from __future__ import annotations

import json
from pathlib import Path

RAW_LIST_DIR = Path('data/raw_list')

CHANNELS = {'character': 233, 'action': 234, 'monster': 235}


def _parse_filter_text(text: str) -> dict:
    """filter.text 是 JSON-string 表示的 list[str],每条形如 'X/Y' 或 'X/X.Z' 多级。

    parse 成 dict[str, list[str]]:'类型' → ['支援牌'] / '花费' → ['花费2']。
    严格契约:JSON 解析失败 raise(数据来源损坏不应静默)。
    """
    if not text:
        return {}
    try:
        items = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f'filter.text JSONDecodeError: {text[:200]!r}') from e
    out: dict[str, list[str]] = {}
    for entry in items:
        if not isinstance(entry, str) or '/' not in entry:
            continue
        cat, val = entry.split('/', 1)
        out.setdefault(cat, []).append(val)
    return out


def _filter_花费_to_int(filter_dict: dict) -> int | None:
    """filter['花费'] = ['花费3'] → 3。'其他花费' → None。"""
    花费_list = filter_dict.get('花费') or []
    if not 花费_list:
        return None
    val = 花费_list[0]
    if val.startswith('花费') and val[2:].isdigit():
        return int(val[2:])
    return None  # '其他花费' 等无明确数字


def _extract_first_url(d: dict, key: str) -> str:
    obj = d.get(key) or {}
    lst = obj.get('list') or []
    return lst[0] if lst else ''


def parse_item_ext(item: dict, channel_id: int) -> dict:
    """从 list API item 抽取规范化 ext 信息。

    严格契约:ext 是 cost 交叉验证独立信源,损坏 ext_str raise(不静默塌缩)。
    """
    ext_str = item.get('ext') or '{}'
    try:
        ext_doc = json.loads(ext_str)
    except json.JSONDecodeError as e:
        cid = item.get('content_id', '?')
        raise ValueError(f'list_ext content_id={cid} ext JSONDecodeError: {ext_str[:200]!r}') from e
    c_dict = ext_doc.get(f'c_{channel_id}') or {}
    filter_text = (c_dict.get('filter') or {}).get('text', '')
    filter_dict = _parse_filter_text(filter_text)
    return {
        'content_id': item.get('content_id'),
        'title': item.get('title', ''),
        'cost_icon_url': _extract_first_url(c_dict, 'costBgIcon'),
        'energy_icon_url': _extract_first_url(c_dict, 'energyBgIcon'),
        'filter_text': filter_text,
        'filter_类型': filter_dict.get('类型') or [],
        'filter_标签': filter_dict.get('标签') or [],
        'filter_花费': _filter_花费_to_int(filter_dict),
        'filter_特殊模式': filter_dict.get('特殊模式') or [],
    }


# load_character_names 已移到 tools.cards.constants
from tools.cards.constants import load_character_names  # noqa: F401 (back-compat)


def load_list_ext_index() -> dict[int, dict]:
    """加载 data/raw_list/{character,action,monster}.json → content_id → parsed ext。

    任一 channel 文件缺失 → raise(必须先跑 fetch_list)。
    """
    index: dict[int, dict] = {}
    for kind, ch in CHANNELS.items():
        fp = RAW_LIST_DIR / f'{kind}.json'
        if not fp.exists():
            raise FileNotFoundError(f'list 数据缺失:{fp};请先跑 .venv/bin/python -m tools.cards.fetch_list')
        items = json.loads(fp.read_text(encoding='utf-8'))
        for it in items:
            cid = it.get('content_id')
            if cid is None:
                continue
            if cid in index:
                raise ValueError(f'list 索引冲突:content_id={cid} 在多 channel 出现')
            index[int(cid)] = parse_item_ext(it, ch)
    return index
