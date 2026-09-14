"""Summarize conditional diagnostics without treating D1 as a perfect teacher."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np


def summarize(directory):
    root = Path(directory)
    result = json.loads((root / 'result.json').read_text())
    if result['status'] != 'complete':
        raise ValueError('incomplete audit')
    for name, sha in result['tool_sha256'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != sha:
            raise ValueError(f'audit implementation changed: {name}')
    games, states = result['games'], result['states']
    assert len(games) == result['scenarios'] * 2
    decisions = [d for g in games for d in g['decisions']]
    wins = [d for d in decisions if d['d1_effect']['wins_now']]
    missed = [d for d in wins if not d['nn_effect']['wins_now']]
    terminal_q = [d['d1_q'] for d in wins]
    summary = {
        'games': len(games),
        'outcomes': dict(Counter(g['outcome'] for g in games)),
        'decisions': len(decisions),
        'divergences': sum(d['nn'] != d['d1'] for d in decisions),
        'positive_f1_gap': sum(d['f1_gap'] > 0 for d in decisions),
        'positive_gap_action_kinds': dict(Counter(d['nn_ref'][0] for d in decisions if d['f1_gap'] > 0)),
        'end_with_skill': sum(d['ends_with_skill'] for d in decisions),
        'payment_only': sum(d['payment_only'] for d in decisions),
        'd1_immediate_win_states': len(wins),
        'not_taking_immediate_win': len(missed),
        'missed_win_game_outcomes': {d['game']: games[d['game']]['outcome'] for d in missed},
        'immediate_win_q': {'negative': sum(q < 0 for q in terminal_q), 'values': terminal_q},
        'branch_states': len(states),
        'continuations': {},
        'limits': 'Visited disagreement states; fixed hidden states; two future seeds; no optimal-value estimate.',
    }
    for mode in ('nn', 'd1'):
        by_game = {}
        values = []
        for state in states:
            pairs = state['continuations'][mode]
            assert len(pairs) == result['repeats']
            assert all(p[name] in (-1, 0, 1) for p in pairs for name in ('nn', 'd1'))
            value = float(np.mean([(p['d1'] - p['nn']) / 2 for p in pairs]))
            values.append(value)
            by_game.setdefault(state['game'], []).append(value)
        # Resample entire source games, retaining correlation between their sampled states.
        rng = np.random.default_rng(118001)
        groups = list(by_game.values())
        totals = np.array([sum(g) for g in groups])
        counts = np.array([len(g) for g in groups])
        indices = rng.integers(len(groups), size=(10000, len(groups)))
        means = totals[indices].sum(1) / counts[indices].sum(1)
        summary['continuations'][mode] = {
            'd1_first_better': sum(v > 0 for v in values),
            'nn_first_better': sum(v < 0 for v in values),
            'equal': sum(v == 0 for v in values),
            'd1_first_delta_score': float(np.mean(values)),
            'source_game_bootstrap_ci95': np.quantile(means, [0.025, 0.975]).tolist(),
        }
    (root / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    summarize(parser.parse_args().directory)
