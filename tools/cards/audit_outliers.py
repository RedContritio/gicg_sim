"""列出 parser 多源验证后所有 outlier / override / 白名单 / 豁免点。

每个 outlier 应在 yaml 中显式记录或 audit 报告中显示。
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from tools.cards.constants import SKILL_PLACEHOLDER_DESC, SURFACE_NAME_MAX_LEN
from tools.cards.overrides import (
    KNOWN_LAYOUT_B_SURFACES,
    KNOWN_LONG_SURFACES,
    load_cost_overrides,
    load_skill_name_overrides,
)


def main() -> int:
    print('# Parser 多源验证后所有 Outlier / Override / 豁免点')

    # 1. cost_overrides
    co = load_cost_overrides()
    print(f'\n## 1. cost_overrides.yaml ({len(co)} 条)')
    print('   cost 多源不一致 user 显式判定 override(per-card per-skill 唯一 by hash)')
    co_doc = yaml.safe_load(Path('data/cards/cost_overrides.yaml').read_text(encoding='utf-8'))
    for entry in co_doc.get('overrides') or []:
        d = entry['conflict_details']
        ref = d.get('card_ref', '?')
        print(f'   - {ref}: {entry["result"]["cost"]} (理由: {d.get("resolution", "")[:80]})')

    # 2. skill_name_overrides
    sn = load_skill_name_overrides()
    print(f'\n## 2. skill_name_overrides.yaml ({len(sn)} 条)')
    print('   wiki tab_name 缺失 user 修复(rename) 或容忍 placeholder(warn)')
    sn_doc = yaml.safe_load(Path('data/cards/skill_name_overrides.yaml').read_text(encoding='utf-8'))
    for entry in sn_doc.get('overrides') or []:
        action = entry.get('action')
        ref = f'{entry["card_id"]}_{entry["card_name"]}({entry["module_kind"]})'
        if action == 'rename':
            print(f'   - {ref} → name="{entry["name"]}"  ({entry.get("why", "")[:60]})')
        else:
            print(f'   - {ref} → {action} (placeholder name 保留)  ({entry.get("why", "")[:60]})')

    # 3. KNOWN_LONG_SURFACES
    print(f'\n## 3. KNOWN_LONG_SURFACES ({len(KNOWN_LONG_SURFACES)} 条)')
    print(f'   term surface name 超过 {SURFACE_NAME_MAX_LEN} 字符的合法长 term(豁免 raise)')
    for s in sorted(KNOWN_LONG_SURFACES, key=len, reverse=True):
        print(f'   - {s} ({len(s)} 字符)')

    # 4. KNOWN_LAYOUT_B_SURFACES
    print(f'\n## 4. KNOWN_LAYOUT_B_SURFACES ({len(KNOWN_LAYOUT_B_SURFACES)} 条)')
    print('   term explanation 不以 "<surface>:" 开头(layout B 或 wiki typo)豁免')
    for s in sorted(KNOWN_LAYOUT_B_SURFACES):
        print(f'   - {s}')

    # 5. character cost icon hash group outliers + placeholder_name skill
    print(f'\n## 5. parser yaml/json 输出中 audit 标记')
    parser_root = Path('data/full')
    if parser_root.is_dir():
        # 5a. _placeholder_name
        placeholders: list[str] = []
        # 5b. character base hash group outliers (从 raw 重 audit)
        hash_groups: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
        for sub in ('character', 'monster'):
            for fp in (parser_root / sub).glob('*.json'):
                try:
                    d = json.loads(fp.read_text(encoding='utf-8'))
                except Exception:
                    continue
                if not isinstance(d, dict):
                    continue

                # placeholder_name skill scan(顶层 + variants)
                def _scan_skills(card_or_var, prefix=''):
                    for sk in card_or_var.get('技能') or []:
                        if sk.get('_placeholder_name'):
                            placeholders.append(f'{sub}/{fp.stem}.{prefix}技能[{sk.get("名称", "?")}]')
                    for sk in card_or_var.get('召唤物') or []:
                        if sk.get('_placeholder_name'):
                            placeholders.append(f'{sub}/{fp.stem}.{prefix}召唤物[{sk.get("名称", "?")}]')

                _scan_skills(d)
                for v in d.get('变体') or []:
                    mode = v.get('模式', 'variant')
                    _scan_skills(v, prefix=f'变体({mode}).')
                # character base hash group
                h = d.get('花费图标URL', '')
                import re

                hm = re.search(r'/([0-9a-f]{32})_\d+\.png', h)
                if hm:
                    hash_groups[hm.group(1)].append((f'{sub}/{fp.stem}', d.get('生命值', 0), d.get('能量上限', 0)))

        print(f'\n   5a. _placeholder_name skill ({len(placeholders)} 张)')
        for p in placeholders:
            print(f'   - {p}')

        outliers_5b = []
        for h, entries in hash_groups.items():
            if len(entries) <= 1:
                continue
            counts: dict[tuple[int, int], int] = defaultdict(int)
            for _, life, energy in entries:
                counts[(life, energy)] += 1
            if len(counts) <= 1:
                continue
            for ref, life, energy in entries:
                if counts[(life, energy)] == 1 and len(entries) >= 5:
                    outliers_5b.append((h[:12], ref, life, energy, dict(counts)))
        print(f'\n   5b. character base hash group outliers ({len(outliers_5b)} 张可疑特例)')
        for h, ref, life, energy, dist in outliers_5b:
            print(f'   - {ref}: (hp,energy)=({life},{energy}) hash {h}.. 同组分布={dist}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
