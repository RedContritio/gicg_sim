"""Across-seed and scenario uncertainty, retaining the shared BC pairing."""

import argparse
import json
from pathlib import Path

import numpy as np

from tools.experiments.semantic_training.compare import compare


def crossed_interval(delta, seed=138000, repeats=10000):
    """Resample both axes; shared scenario samples across models preserve pairing."""
    rng = np.random.default_rng(seed)
    models, scenarios = delta.shape
    means = np.empty(repeats)
    for i in range(repeats):
        chosen_models = rng.integers(models, size=models)
        chosen_scenarios = rng.integers(scenarios, size=scenarios)
        means[i] = delta[np.ix_(chosen_models, chosen_scenarios)].mean()
    return np.quantile(means, [0.025, 0.975]).tolist()


def summarize(root):
    root = Path(root)
    selections = json.loads((root / 'selection.json').read_text())
    reference = root / 'holdout_bc/result.json'
    base = json.loads(reference.read_text())
    n, layouts = base['scenarios'], base['layouts']
    bc = np.array([g['score'] for g in base['games']]).reshape(n, 2, layouts).mean((1, 2))
    panels, deltas, stability = [], [], []
    for row in selections:
        seed = row['seed']
        candidate = root / f'holdout_{seed}/result.json'
        comparison = compare(reference, candidate, root / f'comparison_{seed}.json')
        comparison.update(training_seed=seed, selected_iteration=row['iteration'])
        panels.append(comparison)
        result = json.loads(candidate.read_text())
        deltas.append(np.array([g['score'] for g in result['games']]).reshape(n, 2, layouts).mean((1, 2)) - bc)
        s = json.loads((root / f'stability_{seed}.json').read_text())
        if s['status'] != 'complete':
            raise ValueError('incomplete stability result')
        stability.append(s)
    delta = np.stack(deltas)
    summary = dict(
        status='complete',
        reference_score=base['score'],
        per_seed=panels,
        mean_delta=float(delta.mean()),
        crossed_bootstrap95=crossed_interval(delta),
        fresh_only_mean_delta=float(delta[1:].mean()),
        fresh_only_crossed95=crossed_interval(delta[1:]),
        improvement_seed_count=int((delta.mean(1) > 0).sum()),
        seeds=len(selections),
        per_seed_delta_sd=float(delta.mean(1).std(ddof=1)),
        min_score=min(p['candidate_score'] for p in panels),
        max_score=max(p['candidate_score'] for p in panels),
        logical_agreement=sum(s['logical_equal'] for s in stability) / sum(s['comparisons'] for s in stability),
        payment_agreement=sum(s['payment_equal'] for s in stability) / sum(s['comparisons'] for s in stability),
        stability_states=sum(s['states'] for s in stability),
        q_max_error=max(s['q_max_error'] for s in stability),
        scope='RL randomness conditional on a single fixed supervised initializer; current task only',
    )
    (root / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root')
    summarize(p.parse_args().root)
