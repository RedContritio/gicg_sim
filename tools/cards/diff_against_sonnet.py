"""Compare parser output with the historical reference cleansing set.

Parser output is ``data/full`` JSON with Chinese keys; the reference is
``data/cleaned`` YAML with English keys.

比对核心字段:cost / element / weapon / sub_class / tags / each skill cost / talent cost。
schema key 差异通过 EN_TO_ZH_KEYS 反向映射(parser 中文 ↔ sonnet 英文)。

用法(从 repo root)::

    .venv/bin/python -m tools.cards.diff_against_sonnet
    .venv/bin/python -m tools.cards.diff_against_sonnet --report /tmp/diff.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from tools.cards.constants import EN_TO_ZH_KEYS

# 反向 mapping:sonnet 英文 key → parser 中文 key
_EN_TO_ZH = dict(EN_TO_ZH_KEYS)
_ZH_TO_EN = {v: k for k, v in _EN_TO_ZH.items()}


def get_zh(d: dict, en_key: str):
    """从 parser dict (中文 key) 取值,通过 en→zh 映射。"""
    zh_key = _EN_TO_ZH.get(en_key, en_key)
    return d.get(zh_key)


def cost_normalize(c) -> dict:
    """sonnet cost 用 'same'/'any' 等英文,parser 用 '同色'/'无色' 中文;统一到中文 key 比较。"""
    if not isinstance(c, dict):
        return {}
    en_to_zh = {'same': '同色', 'any': '无色', 'wind': '风', 'fire': '火'}  # sonnet 用拼音 / 英文 / 中文混合
    out = {}
    for k, v in c.items():
        out[en_to_zh.get(k, k)] = v
    return out


def diff_card(parser_card: dict, sonnet_card: dict, card_id: str) -> list[str]:
    diffs = []

    # parent_class
    p_cls = parser_card.get('父类')
    s_cls = sonnet_card.get('parent_class')
    if p_cls != s_cls:
        diffs.append(f'父类: parser={p_cls!r} vs sonnet={s_cls!r}')

    # action 卡:sub_class / tags
    if p_cls == 'action':
        p_sub = parser_card.get('子类')
        s_sub = sonnet_card.get('sub_class')
        if p_sub != s_sub:
            diffs.append(f'子类: parser={p_sub!r} vs sonnet={s_sub!r}')
        p_tags = sorted(parser_card.get('标签') or [])
        s_tags = sorted(sonnet_card.get('tags') or [])
        if p_tags != s_tags:
            diffs.append(f'标签: parser={p_tags} vs sonnet={s_tags}')
        # 顶层 cost
        p_cost = cost_normalize(parser_card.get('花费'))
        s_cost = cost_normalize(sonnet_card.get('cost'))
        if p_cost != s_cost:
            diffs.append(f'cost: parser={p_cost} vs sonnet={s_cost}')

    # character / monster:element / weapon / faction / hp / energy
    if p_cls in ('character', 'monster'):
        for en, zh in [('element', '元素'), ('weapon', '武器'), ('hp', '生命值'), ('energy', '能量上限')]:
            p_v = parser_card.get(zh)
            s_v = sonnet_card.get(en)
            if p_v != s_v:
                diffs.append(f'{en}: parser={p_v!r} vs sonnet={s_v!r}')

        # skills (list)
        p_skills = parser_card.get('技能') or []
        s_skills = sonnet_card.get('skills') or []
        if len(p_skills) != len(s_skills):
            diffs.append(f'skills 数: parser={len(p_skills)} vs sonnet={len(s_skills)}')
        else:
            for i, (ps, ss) in enumerate(zip(p_skills, s_skills)):
                p_name = ps.get('名称')
                s_name = ss.get('name')
                if p_name != s_name:
                    diffs.append(f'skills[{i}].name: parser={p_name!r} vs sonnet={s_name!r}')
                    continue
                p_cost = cost_normalize(ps.get('花费'))
                s_cost = cost_normalize(ss.get('cost'))
                if p_cost != s_cost:
                    diffs.append(f'skills[{i}]({p_name}).cost: parser={p_cost} vs sonnet={s_cost}')

        # talent
        p_talent = parser_card.get('天赋牌')
        s_talent = sonnet_card.get('talent')
        if bool(p_talent) != bool(s_talent):
            diffs.append(f'talent 存在性:parser={bool(p_talent)} vs sonnet={bool(s_talent)}')
        elif p_talent and s_talent:
            p_tc = cost_normalize(p_talent.get('花费'))
            s_tc = cost_normalize(s_talent.get('cost'))
            if p_tc != s_tc:
                diffs.append(f'talent.cost: parser={p_tc} vs sonnet={s_tc}')

    return diffs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--parser-dir', default='data/full')
    ap.add_argument('--sonnet-dir', default='data/cleaned')
    ap.add_argument('--report', default='/tmp/parser_vs_sonnet_diff.md')
    args = ap.parse_args()

    parser_root = Path(args.parser_dir)
    sonnet_root = Path(args.sonnet_dir)
    if not parser_root.is_dir() or not sonnet_root.is_dir():
        print(f'缺目录:parser={parser_root}, sonnet={sonnet_root}', file=sys.stderr)
        return 2

    diffs_by_card: dict[str, list[str]] = {}
    only_parser: list[str] = []
    only_sonnet: list[str] = []
    n_compared = 0
    diff_kind_counter: dict[str, int] = defaultdict(int)

    for sub in ('character', 'action', 'monster'):
        p_files = {fp.stem: fp for fp in (parser_root / sub).glob('*.json')} if (parser_root / sub).is_dir() else {}
        s_files = {fp.stem: fp for fp in (sonnet_root / sub).glob('*.yaml')} if (sonnet_root / sub).is_dir() else {}
        only_parser.extend(f'{sub}/{stem}' for stem in (p_files.keys() - s_files.keys()))
        only_sonnet.extend(f'{sub}/{stem}' for stem in (s_files.keys() - p_files.keys()))
        common = sorted(p_files.keys() & s_files.keys())
        for stem in common:
            n_compared += 1
            try:
                p_card = json.loads(p_files[stem].read_text(encoding='utf-8'))
                s_card = yaml.safe_load(s_files[stem].read_text(encoding='utf-8'))
            except Exception as e:  # noqa: BLE001
                diffs_by_card[f'{sub}/{stem}'] = [f'load error: {e}']
                continue
            if not isinstance(s_card, dict):
                diffs_by_card[f'{sub}/{stem}'] = [f'sonnet yaml 非 dict']
                continue
            diffs = diff_card(p_card, s_card, stem)
            if diffs:
                diffs_by_card[f'{sub}/{stem}'] = diffs
                for d in diffs:
                    # 类别 = ':' 之前的 prefix
                    kind = d.split(':', 1)[0]
                    diff_kind_counter[kind] += 1

    report_lines = [
        f'# Parser vs Sonnet 对拍报告',
        f'',
        f'对比 {n_compared} 张卡;{len(diffs_by_card)} 张有差异。',
        f'仅 parser 有:{len(only_parser)} 张',
        f'仅 sonnet 有:{len(only_sonnet)} 张',
        f'',
        f'## 差异类别汇总',
        f'',
    ]
    for kind, n in sorted(diff_kind_counter.items(), key=lambda x: -x[1]):
        report_lines.append(f'- {kind}: {n} 处')
    if only_parser:
        report_lines.append(f'\n## 仅 parser 有({len(only_parser)})')
        for s in only_parser[:30]:
            report_lines.append(f'- {s}')
    if only_sonnet:
        report_lines.append(f'\n## 仅 sonnet 有({len(only_sonnet)})')
        for s in only_sonnet[:30]:
            report_lines.append(f'- {s}')

    report_lines.append(f'\n## 全部差异详情')
    for card, diffs in sorted(diffs_by_card.items()):
        report_lines.append(f'\n### {card}')
        for d in diffs:
            report_lines.append(f'- {d}')

    Path(args.report).write_text('\n'.join(report_lines), encoding='utf-8')
    print(f'对拍报告:{args.report}', file=sys.stderr)
    print(f'  {n_compared} 张比对;{len(diffs_by_card)} 张有差异', file=sys.stderr)
    print(f'  类别:{dict(diff_kind_counter)}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
