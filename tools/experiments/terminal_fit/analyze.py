"""Paired-layout sensitivity and label sources for a completed isolated fit."""

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.evaluate_history import builder
from tools.experiments.terminal_fit.run import transitions
from training.core.config.loader import load_cfg
from training.paradigms.dmc._episode import collate_batch


def sensitivity(agent, rows):
    changes, logical_changes, label_diff, signs = [], [], [], []
    for row in rows:
        values = []
        for layout in (0, 1):
            batch, _, _ = collate_batch(transitions([row], layout)[:1], device='cpu', max_actions=agent.cfg.max_actions)
            with torch.no_grad():
                values.append(agent.forward_batch(batch)[0][0, : len(row['online_q'][layout])].numpy())
        a, b = values
        changes.append(int(a.argmax()) != int(b.argmax()))
        refs = row['obs'][0]['action_refs']
        logical_changes.append(not np.array_equal(refs[int(a.argmax())], refs[int(b.argmax())]))
        for action, _, _ in row['labels']:
            label_diff.append(abs(float(a[action] - b[action])))
            signs.append(np.sign(a[action]) == np.sign(b[action]))
    return {
        'states': len(rows),
        'greedy_action_changed': sum(changes),
        'logical_action_changed': sum(logical_changes),
        'payment_only_changed': sum(changes) - sum(logical_changes),
        'labeled_q_layout_mae': float(np.mean(label_diff)),
        'labeled_q_sign_agreement': float(np.mean(signs)),
    }


def analyze(config, directory):
    torch.set_num_threads(1)
    root = Path(directory)
    result = json.loads((root / 'result.json').read_text())
    if result['status'] != 'complete':
        raise ValueError('fit not complete')
    rows = torch.load(root / 'dataset.pt', weights_only=False)
    train = [r for r in rows if r['scenario'] < result['split_scenario']]
    test = [r for r in rows if r['scenario'] >= result['split_scenario']]
    agent = builder(load_cfg(config), result['checkpoint'])(0)
    report = {
        'label_modes': dict(Counter(f'{mode}:{y}' for r in rows for _, y, mode in r['labels'])),
        'before': {name: sensitivity(agent, data) for name, data in [('train', train), ('heldout', test)]},
    }
    fitted = torch.load(root / 'diagnostic_weights.pt', weights_only=False)
    assert fitted['diagnostic_only'] and fitted['source_checkpoint_sha256'] == result['checkpoint_sha256']
    agent.net.load_state_dict(fitted['net'])
    report['after'] = {name: sensitivity(agent, data) for name, data in [('train', train), ('heldout', test)]}
    (root / 'layout_analysis.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('directory')
    a = p.parse_args()
    analyze(a.config, a.directory)
