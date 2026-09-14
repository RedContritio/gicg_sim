"""Verify one native strength panel from raw games; not a three-run acceptance claim."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from tools.experiments.semantic_training.teams import eval_cases
from training.core.config.loader import load_cfg


def verify(report, cfg, *, seed, depth, checkpoint_sha256, source_sha256, scenarios=550):
    """Require independently supplied protocol and identity, never infer them from the report."""
    if cfg.scenario.pool != 'native_latest' or cfg.scenario.team_size != 3:
        raise ValueError('expected native three-character configuration')
    if cfg.scenario.random_deck_size != 30 or cfg.scenario.disjoint_teams:
        raise ValueError('expected random legal 30-card decks and overlapping rosters')
    if scenarios < 1 or depth not in (1, 2):
        raise ValueError('invalid panel protocol')
    for digest in (checkpoint_sha256, source_sha256):
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('expected explicit SHA256 identity')
    expected = {
        'status': 'complete',
        'seed': seed,
        'scenarios': scenarios,
        'layouts': 2,
        'opponent_depth': depth,
        'checkpoint_sha256': checkpoint_sha256,
        'scenario': asdict(cfg.scenario),
        'max_game_steps': cfg.paradigm['max_game_steps'],
    }
    for key, value in expected.items():
        if report.get(key) != value:
            raise ValueError(f'panel protocol mismatch: {key}')
    if report.get('provenance', {}).get('source_observation_sha256') != source_sha256:
        raise ValueError('panel source identity mismatch')
    games = report.get('games', [])
    if report.get('variants') or any(g.get('rule_variant', {}).get('variant') for g in games):
        raise ValueError('variant games cannot establish official native strength')
    cases = eval_cases(cfg, seed, scenarios)
    if len(games) != scenarios * 4:
        raise ValueError('incomplete panel')
    expected_keys = [(i, side, layout) for i in range(scenarios) for side in (0, 1) for layout in (0, 1)]
    keys = [(g['index'], g['side'], g['layout']) for g in games]
    if sorted(keys) != expected_keys:
        raise ValueError('duplicate or missing scenario/side/layout')
    by_key = dict(zip(keys, games))
    scores = np.empty((scenarios, 2, 2))
    for i, side, layout in expected_keys:
        g, case = by_key[i, side, layout], cases[i]
        if g['team_0'] != case.team_0 or g['team_1'] != case.team_1:
            raise ValueError('team or character order mismatch')
        if g['win'] not in (0, 1) or g['draw'] != 0 or g['score'] != g['win']:
            raise ValueError('invalid decisive outcome')
        if not re.fullmatch('[0-9a-f]{64}', g.get('trajectory_sha256', '')):
            raise ValueError('missing trajectory identity')
        scores[i, side, layout] = g['score']
    # Layouts are nuisance representations of the same physical game, not extra independent samples.
    for i in range(scenarios):
        for side in (0, 1):
            a, b = by_key[i, side, 0], by_key[i, side, 1]
            if a['trajectory_sha256'] != b['trajectory_sha256'] or a['score'] != b['score']:
                raise ValueError('layout-dependent trajectory or outcome')
    score = float(scores.mean())
    if not np.isclose(report.get('score', np.nan), score, rtol=0, atol=1e-12):
        raise ValueError('summary differs from raw outcomes')
    rng = np.random.default_rng(seed)
    sampled = rng.integers(scenarios, size=(10000, scenarios))
    interval = np.quantile(scores.mean(axis=(1, 2))[sampled].mean(axis=1), [0.025, 0.975])
    return {
        'scope': 'single panel only; independent training and held-out seeds require separate audit',
        'checkpoint_sha256': checkpoint_sha256,
        'source_sha256': source_sha256,
        'seed': seed,
        'opponent_depth': depth,
        'scenarios': scenarios,
        'games': len(games),
        'score': score,
        'cluster_bootstrap95': interval.tolist(),
        'per_side': scores.mean(axis=(0, 2)).tolist(),
        'strength_gate_passed': bool(interval[0] > 0.5 and (depth == 2 or score >= 0.6)),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('report')
    parser.add_argument('output')
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--depth', type=int, choices=(1, 2), required=True)
    parser.add_argument('--checkpoint-sha256', required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    raw = Path(args.report).read_bytes()
    result = verify(
        json.loads(raw),
        load_cfg(args.config),
        seed=args.seed,
        depth=args.depth,
        checkpoint_sha256=args.checkpoint_sha256,
        source_sha256=args.source_sha256,
    )
    result['report_sha256'] = hashlib.sha256(raw).hexdigest()
    Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['strength_gate_passed'] else 1)
