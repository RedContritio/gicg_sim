"""Report population complementarity without assuming a transitive ranking."""

import json
from pathlib import Path
import numpy as np


def summarize(output, members):
    output = Path(output)
    ids = [m['id'] for m in members]
    n = len(ids)
    matrix = np.full((n, n), 0.5)
    intervals = {}
    for i in range(n):
        for j in range(i + 1, n):
            result = json.loads((output / f'pair_{ids[i]}_{ids[j]}.json').read_text())
            assert result['games'] == 64 and result['truncated'] == 0 and result['seed'] == 116000
            matrix[i, j] = result['score']
            matrix[j, i] = 1 - result['score']
            intervals[f'{ids[i]}:{ids[j]}'] = result['paired_score_ci95']
    old_count = n - 2
    old_best = matrix[:old_count, :old_count].max(axis=0)
    proposals = {}
    for role in ('main', 'exploiter'):
        i = ids.index(role)
        improvement = matrix[i, :old_count] - old_best
        proposals[role] = {
            'mean_against_old_pool': float(matrix[i, :old_count].mean()),
            'against_initial': float(matrix[i, ids.index('s43_20000')]),
            'coverage_gain': {ids[j]: float(improvement[j]) for j in range(old_count)},
            'candidate_for_pool': bool((improvement >= 0.05).any()),
            'note': 'Exploratory 64-game estimates; no automatic promotion or deletion.',
        }
    report = {'ids': ids, 'payoff': matrix.tolist(), 'pair_ci95': intervals, 'candidates': proposals}
    (output / 'payoff.json').write_text(json.dumps(report, indent=2))
    lines = [
        '# 小规模策略联赛试跑',
        '',
        '两名训练者各新增6000 frames；独立新优化器和经验池，保留原始锚点。',
        '主策略PFSP权重在本轮开始前确定；针对策略对固定初始主策略训练。仅做一轮扩展，不宣称PSRO收敛。',
        '',
        '|行策略得分|' + '|'.join(ids) + '|',
        '|' + '---|' * (n + 1),
    ]
    for name, row in zip(ids, matrix):
        lines.append('|' + name + '|' + '|'.join(f'{v:.1%}' for v in row) + '|')
    lines += [
        '',
        '候选的平均分仅供描述，是否补充策略池另看各列覆盖增益；正式接纳需复核不确定性。',
        '没有强制要求打赢全部旧模型，没有修改奖励或加入蒸馏，未自动追加训练。',
        '',
        '## 五档基线',
        '',
        '|策略|随机|50%D1|D1|D2|技能滥用者|',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for name in ('s43_20000', 'main', 'exploiter'):
        data = json.loads((output / f'ladder_{name}.json').read_text())
        lines.append('|' + name + '|' + '|'.join(f'{r["score"]:.1%}' for r in data['results'].values()) + '|')
    (output / 'report.md').write_text('\n'.join(lines) + '\n')
    return report
