"""raw JSON → full YAML CLI(strict consumer:完全消化 raw,未访问 paths 报警)。

用法(从 repo root)::

    .venv/bin/python -m tools.cards.cli <raw.json> -o /tmp/test.yaml --coverage
    .venv/bin/python -m tools.cards.cli --raw-dir <dir> --out-dir /tmp/auto_full --coverage
    .venv/bin/python -m tools.cards.cli --raw-dir <dir> --out-dir <dir> --strict

字段实现见:
- ``tools.cards.parse``      — HTML strip / terms / module 解码
- ``tools.cards.extractors`` — cost icon / duration / battle_action / etc
- ``tools.cards.transform``  — character / action / monster transformers
- ``tools.cards.tracker``    — PathTracker 完全消化检查
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from collections import Counter
from pathlib import Path

import yaml

from tools.cards.transform import transform


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--raw-dir', default=None)
    ap.add_argument('--raw-list-dir', type=Path, default=None, help='与详情同快照的目录索引路径')
    ap.add_argument('--out', '-o', default=None)
    ap.add_argument('--out-dir', default='data/full')
    ap.add_argument('--coverage', action='store_true', help='打印 coverage report')
    ap.add_argument('--strict', action='store_true', help='unvisited paths 非空 → exit 1')
    ap.add_argument('--fail-fast', action='store_true', help='第一张 raise 即退出 (默认 batch 收集)')
    ap.add_argument(
        '--format', choices=['json', 'yaml'], default='json', help='输出格式 (默认 json;yaml 兼容旧 sonnet schema)'
    )
    ap.add_argument(
        '--keys',
        choices=['zh', 'en'],
        default='zh',
        help='schema key 语言 (默认 zh 中文;en 输出 parser 内部英文 key,与旧 sonnet schema 兼容)',
    )
    args = ap.parse_args()

    raw_files: list[Path] = list(map(Path, args.paths))
    if args.raw_dir:
        root = Path(args.raw_dir).expanduser()
        for sub in ('character', 'action', 'monster'):
            if (root / sub).is_dir():
                raw_files.extend(p for p in (root / sub).glob('*.json') if p.name != '_index.json')
    if not raw_files:
        print('未指定输入', file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    n_ok, n_strict_fail = 0, 0
    cov_summary: list[tuple[str, int]] = []
    hash_collector: dict[str, list[dict]] = {}  # character cost icon hash → [{card_id, name, raw_life, raw_energy_cap}]

    # B 类豁免 pre-scan:扫所有 raw 收集 cross-card term 表(layout A1 严格的 surface)
    from tools.cards.terms import collect_layout_a_terms, set_known_terms

    known_terms: set[str] = set()
    for p in raw_files:
        try:
            raw = json.loads(p.read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(raw, dict):
            continue
        for m in raw.get('modules', []) or []:
            for c in m.get('components', []) or []:
                try:
                    d = json.loads(c.get('data', '{}'))
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(d, dict):
                    continue
                for html_str in [d.get('rich_text', '') if isinstance(d.get('rich_text'), str) else '']:
                    if html_str:
                        known_terms.update(collect_layout_a_terms(html_str))
                for sk in d.get('list', []) or []:
                    desc = sk.get('desc', {})
                    if isinstance(desc, dict):
                        for v in desc.get('value', []) or []:
                            if v:
                                known_terms.update(collect_layout_a_terms(v))
    set_known_terms(known_terms)
    print(f'pre-scan: {len(known_terms)} 个 term 在 layout A 表中', file=sys.stderr)

    warn_records: list[warnings.WarningMessage] = []
    warnings_ctx = warnings.catch_warnings(record=True)
    caught = warnings_ctx.__enter__()
    warnings.simplefilter('always')
    for p in raw_files:
        try:
            card, cov = transform(p, hash_collector=hash_collector, keys_lang=args.keys, raw_list_dir=args.raw_list_dir)
            if not card:
                print(f'  [skip] {p.name}', file=sys.stderr)
                continue
            cls_key = 'parent_class' if args.keys == 'en' else '父类'
            cls = card[cls_key]
            ext = 'json' if args.format == 'json' else 'yaml'
            if args.out and len(raw_files) == 1:
                out_path = Path(args.out)
            else:
                out_path = out_dir / cls / f'{p.stem}.{ext}'
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                if args.format == 'json':
                    json.dump(card, f, ensure_ascii=False, indent=2)
                else:
                    yaml.safe_dump(card, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
            n_ok += 1

            unvis = cov.get('unvisited_paths', [])
            cov_summary.append((p.name, len(unvis)))
            if args.coverage and unvis:
                print(f'\n# {p.name}: {len(unvis)} unvisited significant paths')
                for path in unvis[:30]:
                    print(f'  - {path}')
                if len(unvis) > 30:
                    print(f'  ... +{len(unvis) - 30} more')
            if args.strict and unvis:
                n_strict_fail += 1
        except Exception as e:  # noqa: BLE001
            print(f'  ✗ {p.name}: {e}', file=sys.stderr)
            if args.fail_fast:
                raise

    warn_records.extend(caught)
    warnings_ctx.__exit__(None, None, None)

    if args.coverage:
        print('\n# Coverage summary (unvisited significant paths per file)')
        for name, n in sorted(cov_summary, key=lambda x: -x[1])[:20]:
            print(f'  {n:>4}  {name}')

    # character cost icon hash 同组验证(独立第二源):同 hash 应同 (hp, energy);outlier 报告
    if hash_collector:
        outliers = []
        for h, entries in hash_collector.items():
            if len(entries) <= 1:
                continue
            tuples = [(e['raw_life'], e['raw_energy_cap']) for e in entries]
            tuple_counts: dict[tuple[int, int], int] = {}
            for t in tuples:
                tuple_counts[t] = tuple_counts.get(t, 0) + 1
            if len(tuple_counts) <= 1:
                continue
            # 多组合:报告 minority(只占 1 张的视为 outlier 候选)
            for e in entries:
                t = (e['raw_life'], e['raw_energy_cap'])
                if tuple_counts[t] == 1 and len(entries) >= 5:
                    outliers.append((h, e, t, dict(tuple_counts)))
        if outliers:
            print(f'\n# Character cost icon hash group outliers ({len(outliers)} 张可疑)', file=sys.stderr)
            for h, e, t, dist in outliers:
                print(
                    f'  hash={h[:12]}.. {e["card_id"]}_{e["name"]}: (life,energy)={t} 同组分布={dist}', file=sys.stderr
                )

    if warn_records:
        # warn 聚合:把"key='X' 子串 'Y' 不符合 expected 'Z'" 这类 message 抽 pattern + count
        kind_counter: Counter = Counter()
        sample_per_kind: dict[str, str] = {}
        for w in warn_records:
            msg = str(w.message)
            # 提取 warn 类别(去掉具体值,保留模式)
            kind = re.sub(r"'[^']*'", "'X'", msg)
            kind = re.sub(r'\d+', 'N', kind)[:160]
            kind_counter[kind] += 1
            if kind not in sample_per_kind:
                sample_per_kind[kind] = msg[:200]
        print(f'\n# Warning summary ({len(warn_records)} 条 warn,{len(kind_counter)} 类)', file=sys.stderr)
        for kind, n in kind_counter.most_common():
            print(f'  [{n:>4}] {kind}', file=sys.stderr)
            print(f'         样本:{sample_per_kind[kind]}', file=sys.stderr)

    print(f'\n完成 {n_ok}/{len(raw_files)},strict-fail={n_strict_fail}', file=sys.stderr)
    return 0 if n_ok == len(raw_files) and (not args.strict or n_strict_fail == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
