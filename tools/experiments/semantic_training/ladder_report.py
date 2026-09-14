"""Recompute paired physical-scenario uncertainty from complete ladder journals."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from tools.experiments.eval_ladder import BASELINES


def report(directory):
    root = Path(directory)
    status = json.loads((root / 'result.json').read_text())
    if status['status'] != 'complete':
        raise ValueError('evaluation is not complete')
    panels = {
        name: [json.loads(line) for line in (root / f'{name}.jsonl').read_text().splitlines()] for name in ('bc', 'rl')
    }
    if any(len(rows) != 7200 for rows in panels.values()):
        raise ValueError('incomplete panel journal')
    results = {}
    for baseline in BASELINES:
        grouped = {}
        for name, rows in panels.items():
            groups = defaultdict(list)
            for r in rows:
                if r['baseline'] == baseline:
                    groups[(r['seed'], r['index'])].append(r)
            if len(groups) != 360 or any(len(v) != 4 for v in groups.values()):
                raise ValueError('missing physical scenarios, sides or layouts')
            grouped[name] = groups
        keys = sorted(grouped['bc'])
        if keys != sorted(grouped['rl']):
            raise ValueError('unpaired scenario seeds')
        delta = []
        for key in keys:
            a, b = grouped['bc'][key], grouped['rl'][key]
            if [(g['side'], g['layout'], g['team_0'], g['team_1']) for g in a] != [
                (g['side'], g['layout'], g['team_0'], g['team_1']) for g in b
            ]:
                raise ValueError('unpaired team or layout identities')
            delta.append(np.mean([g['win'] for g in b]) - np.mean([g['win'] for g in a]))
        delta = np.asarray(delta).reshape(3, 120)
        # Preserve equal weight of the three predeclared seeds in each bootstrap draw.
        rng = np.random.default_rng(147101)
        draws = np.stack([delta[i][rng.integers(120, size=(10000, 120))].mean(axis=1) for i in range(3)])
        results[baseline] = {
            'bc': status['panels']['bc']['results'][baseline],
            'rl': status['panels']['rl']['results'][baseline],
            'paired_delta': float(delta.mean()),
            'paired_stratified_ci95': np.quantile(draws.mean(axis=0), [0.025, 0.975]).tolist(),
            'paired_stratified_ci99': np.quantile(draws.mean(axis=0), [0.005, 0.995]).tolist(),
        }
    output = {
        'status': 'complete',
        'source_result_sha256': hashlib.sha256((root / 'result.json').read_bytes()).hexdigest(),
        'results': results,
        'journal_sha256': {name: hashlib.sha256((root / f'{name}.jsonl').read_bytes()).hexdigest() for name in panels},
    }
    (root / 'summary.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(
        {
            name: {
                'bc': r['bc']['score'],
                'rl': r['rl']['score'],
                'ci': r['rl']['ci95'],
                'delta': r['paired_delta'],
                'delta_ci': r['paired_stratified_ci95'],
            }
            for name, r in results.items()
        }
    )
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory')
    report(p.parse_args().directory)
