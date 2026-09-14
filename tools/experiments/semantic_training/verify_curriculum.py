"""Recompute frozen full-pool acceptance gates from physical-game records."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from tools.experiments.semantic_training.deck_curriculum import card_grades
from training.core.config.loader import load_cfg


def checked_panel(panel, candidate, seed, depth):
    if panel['status'] != 'complete' or panel['checkpoint_sha256'] != candidate['sha256']:
        raise ValueError('incomplete panel or candidate mismatch')
    if (panel['seed'], panel['opponent_depth'], panel['scenarios'], panel['layouts']) != (seed, depth, 720, 2):
        raise ValueError('unexpected final evaluation protocol')
    rows = panel['games']
    identities = [(r['index'], r['side'], r['layout']) for r in rows]
    expected = [(i, side, layout) for i in range(720) for side in (0, 1) for layout in (0, 1)]
    if identities != expected:
        raise ValueError('missing, duplicated or reordered games')
    if any(r['draw'] or r['score'] not in (0, 1) or r['score'] != r['win'] for r in rows):
        raise ValueError('nondecisive or inconsistent game result')
    pairs = Counter(r['matchup'] for r in rows)
    if len(pairs) != 15 or len(set(pairs.values())) != 1:
        raise ValueError('unbalanced matchup coverage')
    values = np.array([r['score'] for r in rows]).reshape(720, 2, 2)
    if not np.array_equal(values[:, :, 0], values[:, :, 1]):
        raise ValueError('layout-dependent outcome')
    physical = values.mean(axis=(1, 2))
    rng = np.random.default_rng(319000)
    interval = np.quantile(physical[rng.integers(720, size=(10000, 720))].mean(1), [0.025, 0.975]).tolist()
    if abs(float(physical.mean()) - panel['score']) > 1e-12:
        raise ValueError('summary score disagrees with raw games')
    return dict(score=float(physical.mean()), independently_recomputed95=interval, passes=interval[0] > 0.5)


def run(directory):
    root = Path(directory)
    status = json.loads((root / 'result.json').read_text())
    if status['status'] != 'complete' or [s['level'] for s in status['stages']] != [3, 4, 5, 6]:
        raise ValueError('curriculum stages not complete')
    cfg = load_cfg('configs/dmc/curriculum_l6.toml')
    if cfg.scenario.random_deck_size != 30 or not set(card_grades()) <= set(cfg.scenario.card_pool):
        raise ValueError('final environment does not cover full 30-card curriculum')
    if [item['seed'] for item in status['final']] != [271000, 281000, 291000]:
        raise ValueError('missing independent training seeds')
    results = []
    for item in status['final']:
        checkpoint = Path(item['candidate'])
        if not checkpoint.is_file() or hashlib.sha256(checkpoint.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('frozen checkpoint missing or changed; run verifier on artifact host')
        subdir = root / f'acceptance_{item["seed"]}'
        row = {'seed': item['seed']}
        for depth in (1, 2):
            panel = json.loads((subdir / f'rl_d{depth}/result.json').read_text())
            if panel['provenance']['source_observation_sha256'] != status['provenance']['source_observation_sha256']:
                raise ValueError('panel source differs from curriculum source')
            row[f'd{depth}'] = checked_panel(panel, item, item['seed'] + 3000, depth)
        stability = json.loads((subdir / 'stability.json').read_text())
        if (
            stability['status'] != 'complete'
            or stability['logical_agreement'] != 1
            or stability['payment_agreement'] != 1
        ):
            raise ValueError('layout stability gate failed')
        results.append(row)
    result = dict(
        status='verified',
        candidates=results,
        strength_gate_passed=all(r[f'd{d}']['passes'] for r in results for d in (1, 2)),
        remaining='Candidate card-use coverage audit and final report still required.',
    )
    (root / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    run(parser.parse_args().directory)
