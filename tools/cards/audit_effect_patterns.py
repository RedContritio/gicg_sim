"""扫所有 cleansed yaml 的 effect_text,按句子做 normalize 后聚类频次。

用途:为 dsl_gaps audit 提供 evidence-based 数据,而非 sqrt(N) 估算。

normalize 规则(strict-token 转换器白名单的前置工作):
- 数字 → N(token-level placeholder)
- 元素名(风火雷冰水草岩)+元素 → ELEM元素 / ELEM(单字)
- 角色名(从 cleaned/character/ 列出)→ CHAR
- 卡名(从 cleaned/action/ 列出)→ CARD
- 「...」内含术语 → 「TERM」(若 surface 在 _glossary.yaml 中)

输出:
- top-N 句式频次表(stdout 或 markdown)
- pattern 分桶:可严格匹配的(数值/元素/draw/heal/damage/dice 等基础动词) vs 复杂

用法(从 repo root)::

    .venv/bin/python -m tools.cards.audit_effect_patterns
    .venv/bin/python -m tools.cards.audit_effect_patterns --output /tmp/eff.md --top 200
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

CLEANED = Path('data/cleaned')
ELEMENTS = ['风', '火', '雷', '冰', '水', '草', '岩']

# 细分:句子拆分用 [。\n;；]+(中文句号 + 换行 + 分号变体);保留括号内整体
_SPLIT_RE = re.compile(r'[。\n;；]+')
# 数字 → N(整数,不动小数;effect text 几乎全整数)
_NUM_RE = re.compile(r'\d+')
# 「X」/「Y」中的术语(多变,先剥) → 替成「TERM」
_BRACKET_TERM_RE = re.compile(r'「[^」]{1,20}」')
# 元素名+元素 → ELEM元素
_ELEM_TOKEN_RE = re.compile('[' + ''.join(ELEMENTS) + ']元素')


def load_known_chars() -> set[str]:
    out: set[str] = set()
    for p in (CLEANED / 'character').glob('*.yaml'):
        try:
            doc = yaml.safe_load(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        if isinstance(doc, dict):
            n = doc.get('name', '').strip()
            if n:
                out.add(n)
    return out


def load_known_cards() -> set[str]:
    out: set[str] = set()
    for sub in ('action',):
        for p in (CLEANED / sub).glob('*.yaml'):
            try:
                doc = yaml.safe_load(p.read_text(encoding='utf-8'))
            except Exception:
                continue
            if isinstance(doc, dict):
                n = doc.get('name', '').strip()
                if n:
                    out.add(n)
    return out


def normalize_sentence(s: str, chars: set[str], cards: set[str]) -> str:
    """对单句做 normalize,结果作为 frequency key。"""
    s = s.strip()
    if not s:
        return ''
    s = _BRACKET_TERM_RE.sub('「TERM」', s)
    s = _ELEM_TOKEN_RE.sub('ELEM元素', s)
    # 单元素字(独立出现,不在「」内)→ ELEM
    for e in ELEMENTS:
        # 非「内」非元素后缀的单字元素出现(如 "造成X火伤害" → "造成X ELEM 伤害")
        # 简化:只 strip 单字 element 紧贴数字前后 + 在"伤害"/"附着"/"骰"前的
        s = re.sub(rf'(?<![一-鿿]){re.escape(e)}(?=元素|伤害|附着|骰|属性|盾|护盾)', 'ELEM', s)
    # 角色名(长名优先)
    for n in sorted(chars, key=len, reverse=True):
        if n in s:
            s = s.replace(n, 'CHAR')
    # 卡名(长名优先,但避免与术语撞 — 术语已经被 「TERM」 处理掉了)
    for n in sorted(cards, key=len, reverse=True):
        if n in s and len(n) >= 3:
            s = s.replace(n, 'CARD')
    s = _NUM_RE.sub('N', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def collect_effect_texts() -> list[tuple[str, str]]:
    """Return ``(source_id, effect_text)`` for every cleansed effect.

    Sources include top-level actions plus character/monster skills,
    summons, and talents.
    """
    out: list[tuple[str, str]] = []
    for sub in ('action', 'character', 'monster'):
        d = CLEANED / sub
        if not d.is_dir():
            continue
        for p in d.glob('*.yaml'):
            try:
                doc = yaml.safe_load(p.read_text(encoding='utf-8'))
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            cid = doc.get('id', p.stem)
            cname = doc.get('name', '')
            base = f'{sub}/{cid}_{cname}'
            t = doc.get('effect_text', '') or ''
            if t.strip():
                out.append((f'{base}#main', t))
            for kind in ('skills', 'summons'):
                for i, item in enumerate(doc.get(kind, []) or []):
                    if isinstance(item, dict):
                        t = item.get('effect_text', '') or ''
                        if t.strip():
                            out.append((f'{base}#{kind}[{i}]', t))
            talent = doc.get('talent')
            if isinstance(talent, dict):
                t = talent.get('effect_text', '') or ''
                if t.strip():
                    out.append((f'{base}#talent', t))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='/tmp/effect_patterns.md')
    ap.add_argument('--top', type=int, default=200)
    ap.add_argument('--min-count', type=int, default=2, help='只显示出现 >= N 次的 pattern')
    args = ap.parse_args()

    chars = load_known_chars()
    cards = load_known_cards()
    print(f'loaded {len(chars)} char names, {len(cards)} card names', file=sys.stderr)

    effects = collect_effect_texts()
    print(f'collected {len(effects)} effect_text blocks', file=sys.stderr)

    sentence_counter: Counter = Counter()
    sentence_examples: dict[str, list[str]] = {}
    n_sentences = 0
    for src, text in effects:
        for raw_sent in _SPLIT_RE.split(text):
            raw_sent = raw_sent.strip()
            if not raw_sent or len(raw_sent) < 3:
                continue
            n_sentences += 1
            norm = normalize_sentence(raw_sent, chars, cards)
            if not norm:
                continue
            sentence_counter[norm] += 1
            sentence_examples.setdefault(norm, []).append(f'{src}: {raw_sent[:80]}')
    print(f'split into {n_sentences} sentences, {len(sentence_counter)} unique normalized', file=sys.stderr)

    lines: list[str] = []
    lines.append(f'# effect_text pattern frequency (top {args.top} normalized)')
    lines.append('')
    lines.append(f'- 输入 effect blocks: {len(effects)}')
    lines.append(f'- 句子总数(split by 。\\n;): {n_sentences}')
    lines.append(f'- 去重后 normalized pattern: {len(sentence_counter)}')
    lines.append(f'- normalize 规则: 数字→N / 元素→ELEM / 角色名→CHAR / 卡名→CARD / 「术语」→「TERM」')
    lines.append('')
    lines.append('| 频次 | normalized pattern | 第一例 |')
    lines.append('|------|--------------------|--------|')
    for norm, n in sentence_counter.most_common(args.top):
        if n < args.min_count:
            break
        ex = (sentence_examples[norm][0] if norm in sentence_examples else '')[:120]
        norm_display = norm.replace('|', '\\|')[:80]
        ex_display = ex.replace('|', '\\|')
        lines.append(f'| {n} | `{norm_display}` | {ex_display} |')

    Path(args.output).write_text('\n'.join(lines), encoding='utf-8')
    print(f'written {args.output} ({len(lines)} lines)', file=sys.stderr)

    # stdout 简短 summary
    total = sum(sentence_counter.values())
    top10 = sentence_counter.most_common(10)
    print(
        f'\ntop-10 patterns cover {sum(n for _, n in top10)}/{total} = {sum(n for _, n in top10) / total:.1%} of sentences'
    )
    for norm, n in top10:
        print(f'  {n:>5}  {norm[:80]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
