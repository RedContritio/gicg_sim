"""raw → full yaml dispatch:character / action / monster。

子模块:
- ``tools.cards.character`` — character transformer
- ``tools.cards.action``    — action transformer
- ``tools.cards.parse``     — html / terms / module 解码
- ``tools.cards.extractors`` — 字段 extractors
- ``tools.cards.tracker``   — PathTracker 完全消化检查
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.cards.action import transform_action
from tools.cards.character import transform_character
from tools.cards.constants import translate_keys
from tools.cards.list_ext import load_list_ext_index
from tools.cards.parse import PARENT_CLASS
from tools.cards.tracker import PathTracker, coverage_report


def transform_monster(
    raw: dict,
    raw_path: Path,
    raw_text: str,
    tracker: PathTracker,
    list_ext: dict | None,
    hash_collector: dict | None = None,
) -> dict:
    """monster schema 与 character 同,只 parent_class 不同;skill cost 不走 character 模板。

    严格契约:monster 不应有 talent / variant module(语义上怪物没天赋牌或自行巧局变体);
    raw 含此 module → raise。
    """
    for m in raw.get('modules', []) or []:
        if m.get('name') == '天赋牌':
            raise ValueError(f'monster {raw.get("name")!r} 不应含 天赋牌 module(raw_path={raw_path})')
    out = transform_character(
        raw, raw_path, raw_text, tracker, list_ext, is_monster=True, hash_collector=hash_collector
    )
    out['parent_class'] = 'monster'
    if out.get('variants') or out.get('自行巧局') or out.get('jiqiao'):
        raise ValueError(f'monster {raw.get("name")!r} 不应含 variant / jiqiao(raw_path={raw_path})')
    return out


def transform(
    raw_path: Path,
    hash_collector: dict | None = None,
    keys_lang: str = 'zh',
    *,
    raw_list_dir: Path | None = None,
) -> tuple[dict | None, dict]:
    """raw json → 规范化 dict。从 data/raw_list/ 自动 join 对应 list ext。

    keys_lang:
      'zh' (默认) — 出口翻译成中文 key (mihoyo wiki 风格)
      'en'        — 保留 parser 内部的英文 key (与旧 sonnet schema 兼容)
    """
    raw_text = raw_path.read_text(encoding='utf-8')
    raw = json.loads(raw_text)
    tracker = PathTracker(raw)
    parent_class = ''
    for menu in raw.get('menus', []) or []:
        if cls := PARENT_CLASS.get(menu.get('name', '')):
            parent_class = cls
            break

    cid = raw.get('id')
    try:
        cid_int = int(cid)
    except (TypeError, ValueError) as e:
        raise ValueError(f'card id={cid!r} 无法转 int (raw_path={raw_path})') from e
    list_ext_index = load_list_ext_index(raw_list_dir)
    list_ext = list_ext_index.get(cid_int)
    if list_ext is None:
        raise ValueError(
            f'list_ext 缺失:content_id={cid_int} (raw_path={raw_path}) 在 data/raw_list/* 中找不到;'
            '请先跑 .venv/bin/python -m tools.cards.fetch_list 更新 list 数据'
        )

    if parent_class == 'character':
        out = transform_character(raw, raw_path, raw_text, tracker, list_ext, hash_collector=hash_collector)
    elif parent_class == 'action':
        out = transform_action(raw, raw_path, raw_text, tracker, list_ext)
    elif parent_class == 'monster':
        out = transform_monster(raw, raw_path, raw_text, tracker, list_ext, hash_collector=hash_collector)
    else:
        return None, {'error': 'unknown parent_class'}
    if keys_lang == 'zh':
        out = translate_keys(out)
    cov = coverage_report(raw, tracker.visited)
    return out, cov
