"""Summarize paired counterfactual rows and flag partial reroll roots."""

import argparse
from collections import Counter
import json
from pathlib import Path

import torch


def _values(rows, key):
    return [row[key] for row in rows]


def _stats(rows):
    if not rows:
        return {'rows': 0}
    weights = _values(rows, 'sample_weight')
    differences = _values(rows, 'mean_difference')
    return {
        'rows': len(rows),
        'sides': dict(Counter(str(row['learner_side']) for row in rows)),
        'preferences': dict(Counter(str(row['preference']) for row in rows)),
        'ties': sum(row['ties'] for row in rows),
        'non_tie_pairs': sum(row['pair_repeats'] - row['ties'] for row in rows),
        'discordance': sum(row['discordance'] for row in rows),
        'weight_distribution': dict(Counter(str(value) for value in weights)),
        'weight_mean': sum(weights) / len(weights),
        'mean_difference_min': min(differences),
        'mean_difference_max': max(differences),
        'mean_difference_mean': sum(differences) / len(differences),
    }


def audit(directory):
    rows = []
    for path in sorted(Path(directory).glob('paired_*.pt')):
        rows.extend(torch.load(path, weights_only=False))
    by_type = {kind: [row for row in rows if row['decision_type'] == kind] for kind in ('reroll', 'ordinary')}
    reroll = by_type['reroll']
    partial = 0
    confirmation = 0
    differing_counts = 0
    colors = Counter()
    for row in reroll:
        refs = row['obs']['action_refs']
        chosen = [int(value) for value in refs[row['chosen_action']]]
        alternative = [int(value) for value in refs[row['alternative_action']]]
        colors[str(chosen[2])] += 1
        if chosen[2] == 8 and alternative[2] == 8:
            confirmation += 1
        else:
            partial += 1
        if chosen[1] != alternative[1]:
            differing_counts += 1
    return {
        'rows': len(rows),
        'by_decision_type': {kind: _stats(items) for kind, items in by_type.items()},
        'reroll_action_colors': dict(colors),
        'reroll_partial_color_rows': partial,
        'reroll_confirmation_rows': confirmation,
        'reroll_differing_count_rows': differing_counts,
        'reroll_rng_alignment_required': bool(partial and differing_counts),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rollout_directory')
    args = parser.parse_args()
    print(json.dumps(audit(args.rollout_directory), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
