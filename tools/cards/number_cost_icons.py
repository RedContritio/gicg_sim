"""按 mapping 中分组数排序,给每张 cost icon 编号 (01..NN)。

输出:
- data/cost_icons/<NN>.png — 重命名后的图(原图删除)
- data/cost_icons/_index.yaml — index → {hash, n_cards, samples, current_costs}
- data/cost_icons/_judgement.yaml — 让 user 填的判定模板,key 是序号
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> int:
    icons_dir = Path('data/cost_icons')
    mapping_path = icons_dir / '_mapping.yaml'
    if not mapping_path.exists():
        print('mapping 不存在,先跑 tools.dl_cost_icons', file=sys.stderr)
        return 1

    mapping = yaml.safe_load(open(mapping_path, encoding='utf-8'))
    groups = sorted(mapping.items(), key=lambda kv: -len(kv[1]))

    index: dict[str, dict] = {}
    judgement_lines: list[str] = [
        '# 看 data/cost_icons/<NN>.png 后,在每个 NN 后填判定。',
        '# 选项:',
        '#   无色 N      任意 N',
        '#   同色 N      同色 N',
        '#   <元素> N    指定元素(风/火/雷/冰/水/草/岩),通常 N=1',
        '#   无色 0      零 cost',
        '#   mixed       此图同时被 same/any 用,需 case-by-case',
        '',
        'judgements:',
    ]

    for i, (h, cards) in enumerate(groups, start=1):
        nn = f'{i:02d}'
        # rename file
        old = icons_dir / f'{h}.png'
        new = icons_dir / f'{nn}.png'
        if old.exists():
            old.rename(new)

        # collect distinct existing costs for context
        cur = sorted({str(c['cost']) for c in cards if c.get('cost') and c.get('cost') != '?'})
        samples = [c['name'] for c in cards[:3]]

        index[nn] = {
            'hash': h,
            'n_cards': len(cards),
            'samples': samples,
            'current_costs': cur,
        }

        cur_s = ' / '.join(cur) if cur else '<all uncleansed>'
        judgement_lines.append(f'  {nn}:        # n={len(cards)}  cur={cur_s}  e.g. {", ".join(samples)}')

    with open(icons_dir / '_index.yaml', 'w', encoding='utf-8') as f:
        yaml.safe_dump(index, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    with open(icons_dir / '_judgement.yaml', 'w', encoding='utf-8') as f:
        f.write('\n'.join(judgement_lines))

    print(f'numbered {len(groups)} icons → 01.png .. {len(groups):02d}.png', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
