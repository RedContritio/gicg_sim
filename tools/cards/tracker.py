"""PathTracker — 跟踪 raw dict 中哪些 path 被消耗,哪些未被访问。

设计:walk raw dict,把每个 leaf path 记到 ``all_paths``(全集)。
工具消耗时调 ``tracker.visit(path)`` 把 path 加到 ``visited``。
``unvisited = all_paths - visited`` 即未消化 paths;
其中在 ``KNOWN_NON_DATA_PATTERNS`` 白名单内的视为 wiki 系统字段(audit / visual / CMS),
其余即 schema 缺失(应进 yaml 但工具没读)。

cli ``--strict`` 模式下,unvisited 非空 (= schema 缺失) → exit 1。
"""

from __future__ import annotations

import re
from typing import Any


# 已知不进 yaml 的 wiki 系统字段(positive whitelist:显式声明这些 path 不用消化)。
# 任何未访问且不在此白名单的 path 视为 schema 缺失(parser 应改 visit 该字段或 KNOWN_NON_DATA_PATTERNS 加补)。
# 路径用 dot path,数组下标统一写为 [*]。
KNOWN_NON_DATA_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p)
    for p in [
        r'^header_img_url$',
        r'^icon_url$',  # 顶层卡 icon(已在 yaml 顶层保留)
        # wiki 系统/CMS 字段(无卡牌语义)
        r'^alias_name$',
        r'^beta$',
        r'^correct_lock_status$',
        r'^ext($|\.)',  # ext.* (post_ext / fe_ext / server_ext / scrolling_text / corner_mark / personalized_color)
        r'^filter_values$',
        r'^langs?$',
        r'^langs\[\]$',
        r'^menu_id$',
        r'^menu_name$',
        r'^menu_style$',
        r'^page_type$',
        r'^status$',
        r'^template_id$',
        r'^template_layout($|\.)',
        # raw 顶层的 menus[] 是分类菜单,只取 parent_class
        r'^menus\[\*\]\.(?!name$)',  # menus 里非 name 的字段(id/icon/path/...)
        r'^modules\[\*\]\.(?:id|is_poped|repeated|switch|is_show_switch|is_submodule|origin_module_id|without_border|can_delete|is_hidden|rich_text_editing|is_customize_name|is_abstract|desc)$',
        r'^modules\[\*\]\.components\[\*\]\.(?:component_id|layout|style|ch_ext|fe_ext|template_layout|content_size|template_module_id|order)$',
        # 卡级别一些 wiki audit 字段
        r'^update_time$',
        r'^bbs_audit_status$',
        r'^update_user_id$',
        r'^content_id$',
        r'^correct_status$',
        r'^edit_lock_status$',
        r'^bind_attr$',
        r'^scoring$',
        r'^content_lock$',
        r'^display_field$',
        r'^module_lock_status$',
        r'^content_status$',
        r'^channel_id$',
        r'^bbs_appraise_status$',
        r'^cover_pic$',
        r'^update_id$',
        r'^link_to_app$',
        r'^link_to$',
        r'^contributors$',
        r'^summary$',
        r'^channel_route_id$',
        r'^correct_user_id$',
        r'^reply_status$',
        r'^reservation_status$',
        r'^app_appraise_status$',
        r'^app_audit_status$',
        r'^trans_status$',
        r'^source_link$',
        r'^url_path$',
        r'^check_status$',
        r'^reply_count$',
        r'^view_count$',
        r'^like_count$',
        r'^create_time$',
        r'^content_status_int$',
        r'^updator$',
        r'^creator$',
        r'^repo$',
        r'^create_user_id$',
        r'^bbs_id$',
        r'^bbs_app_audit_status$',
        r'^score$',
        r'^lang$',
        r'^app_lang$',
        r'^correct_lock$',
        r'^edit_lock$',
        r'^audit_lock$',
        r'^contributor$',
        r'^id$',  # 顶层 id 已用
    ]
]


def _walk_paths(obj: Any, prefix: str, out: set[str]) -> None:
    """收集 obj 中所有 leaf path(dict 的 key 也作 leaf 计,防止整个 subtree 被 skip)。"""
    if isinstance(obj, dict):
        if not obj:
            out.add(prefix or '<root>')
            return
        for k, v in obj.items():
            sub = f'{prefix}.{k}' if prefix else k
            out.add(sub)
            _walk_paths(v, sub, out)
    elif isinstance(obj, list):
        if not obj:
            out.add(prefix + '[]')
            return
        # 对 list,合并所有 element 的 paths(用 [*] 占位)
        for item in obj:
            sub = prefix + '[*]'
            _walk_paths(item, sub, out)
    else:
        if not prefix:
            out.add('<root>')


def collect_all_paths(raw: Any) -> set[str]:
    paths: set[str] = set()
    _walk_paths(raw, '', paths)
    return paths


def is_known_non_data(path: str) -> bool:
    """path 是否在已知"非数据"白名单内(wiki audit / CMS / visual,不进 yaml)。"""
    return any(p.search(path) for p in KNOWN_NON_DATA_PATTERNS)


class PathTracker:
    """记录访问到的 path。每次工具读 raw 字段,调 .visit(path)。"""

    def __init__(self, raw: Any) -> None:
        self.raw = raw
        self.all_paths = collect_all_paths(raw)
        self.visited: set[str] = set()

    def visit(self, path: str) -> None:
        # 一并标记 path 的所有前缀(dict 的子 key 访问视为父也访问)
        parts = re.split(r'(\[\*\]|\.)', path)
        cur = ''
        for p in parts:
            cur += p
            if cur:
                self.visited.add(cur)

    def unvisited(self) -> list[str]:
        return sorted(p for p in (self.all_paths - self.visited) if not is_known_non_data(p))


def coverage_report(raw: Any, visited: set[str]) -> dict:
    all_p = collect_all_paths(raw)
    unvis = [p for p in (all_p - visited) if not is_known_non_data(p)]
    return {
        'total': len(all_p),
        'visited': len(visited),
        'unvisited_significant': len(unvis),
        'unvisited_paths': sorted(unvis),
    }
