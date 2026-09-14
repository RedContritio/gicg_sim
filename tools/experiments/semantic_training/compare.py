"""Paired physical-scenario comparison of two frozen evaluated policies."""

import argparse
import json
from pathlib import Path

import numpy as np


def compare(reference, candidate, output):
    a, b = (json.loads(Path(p).read_text()) for p in (reference, candidate))
    for key in ('seed', 'scenarios', 'layouts'):
        if a[key] != b[key]:
            raise ValueError(f'unpaired evaluation: {key}')
    if a.get('opponent_depth', 1) != b.get('opponent_depth', 1):
        raise ValueError('unpaired evaluation: opponent')
    if a['provenance']['source_observation_sha256'] != b['provenance']['source_observation_sha256']:
        raise ValueError('unpaired evaluation: environment fingerprint')
    if a['status'] != 'complete' or b['status'] != 'complete':
        raise ValueError('incomplete evaluation')
    for key in ('scenario', 'max_game_steps'):
        if a.get(key) != b.get(key):
            raise ValueError(f'unpaired evaluation: {key}')
    if bool(a.get('variants')) != bool(b.get('variants')):
        raise ValueError('unpaired evaluation: native versus variant')

    def identities(r):
        return [(g['index'], g['side'], g['layout'], g.get('team_0'), g.get('team_1')) for g in r['games']]

    if identities(a) != identities(b):
        raise ValueError('game order mismatch')
    n, layouts = a['scenarios'], a['layouts']
    expected = [(i, side, layout) for i in range(n) for side in (0, 1) for layout in range(layouts)]
    for report in (a, b):
        if [(g['index'], g['side'], g['layout']) for g in report['games']] != expected:
            raise ValueError('missing, duplicated or unordered game identities')
    for x, y in zip(a['games'], b['games']):
        if x.get('rule_variant') != y.get('rule_variant'):
            raise ValueError('unpaired evaluation: rule variant manifest')
    arrays = [np.array([g['score'] for g in r['games']]).reshape(n, 2, layouts) for r in (a, b)]
    for report, scores in zip((a, b), arrays):
        if not np.isfinite(scores).all() or not ((scores >= 0) & (scores <= 1)).all():
            raise ValueError('invalid game scores')
        if not np.isclose(report['score'], scores.mean(), rtol=0, atol=1e-12):
            raise ValueError('summary differs from raw game scores')
    delta = (arrays[1] - arrays[0]).mean(axis=(1, 2))
    rng = np.random.default_rng(130001)
    sampled = rng.integers(n, size=(10000, n))
    result = {
        'reference': a['checkpoint'],
        'candidate': b['checkpoint'],
        'reference_sha256': a['checkpoint_sha256'],
        'candidate_sha256': b['checkpoint_sha256'],
        'seed': a['seed'],
        'scenarios': n,
        'layouts': layouts,
        'reference_score': a['score'],
        'candidate_score': b['score'],
        'delta': float(delta.mean()),
        'paired_cluster95': np.quantile(delta[sampled].mean(axis=1), [0.025, 0.975]).tolist(),
        'reference_side_score': arrays[0].mean(axis=(0, 2)).tolist(),
        'candidate_side_score': arrays[1].mean(axis=(0, 2)).tolist(),
        'reference_per_layout': a['per_layout'],
        'candidate_per_layout': b['per_layout'],
    }
    Path(output).write_text(json.dumps(result, indent=2))
    print(result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('reference')
    p.add_argument('candidate')
    p.add_argument('output')
    a = p.parse_args()
    compare(a.reference, a.candidate, a.output)
