"""Fit mixed terminal labels in an isolated NN; evaluate held-out states and layouts."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random

import numpy as np
import torch

from tools.experiments.evaluate_history import builder
from tools.experiments.terminal_fit.collect import collect
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.paradigms.dmc._episode import collate_batch
from training.paradigms.dmc.buffer import DmcTransition


def transitions(rows, layout):
    return [DmcTransition(r['obs'][layout], a, float(y)) for r in rows for a, y, _ in r['labels']]


def evaluate(agent, rows, layout):
    errors, targets, predictions, gaps = [], [], [], []
    ranked, count = 0, 0
    with torch.no_grad():
        for r in rows:
            ts = transitions([r], layout)
            batch, _, _ = collate_batch(ts[:1], device='cpu', max_actions=agent.cfg.max_actions)
            q = agent.forward_batch(batch)[0][0].cpu().numpy()
            for a, y, _ in r['labels']:
                predictions.append(float(q[a]))
                targets.append(y)
                errors.append(float((q[a] - y) ** 2))
            gaps.append(float(np.max(np.abs(q[: len(r['online_q'][layout])] - r['online_q'][layout]))))
            ys = {y for _, y, _ in r['labels']}
            if -1 in ys and 1 in ys:
                count += 1
                ranked += max(q[a] for a, y, _ in r['labels'] if y == 1) > max(
                    q[a] for a, y, _ in r['labels'] if y == -1
                )
    p, y = np.array(predictions), np.array(targets)
    return {
        'states': len(rows),
        'labels': len(y),
        'mse': float(np.mean(errors)),
        'sign_accuracy': float(np.mean(np.sign(p) == y)),
        'class_mse': {str(k): float(np.mean((p[y == k] - k) ** 2)) for k in sorted(set(targets))},
        'mixed_state_correct': int(ranked),
        'mixed_states': count,
        'max_difference_from_original_online_q': max(gaps),
    }


def run(config, checkpoint, output, scenarios=8, steps=400):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(119000)
    cfg = load_cfg(config)
    sha = hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest()
    result = {
        'status': 'collecting',
        'provenance': provenance(),
        'checkpoint': checkpoint,
        'checkpoint_sha256': sha,
        'seed': 119000,
        'steps': steps,
        'tool_sha256': {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path('tools/experiments/terminal_fit').glob('*.py'))
        },
    }

    def save():
        tmp = root / 'result.tmp'
        tmp.write_text(json.dumps(result, indent=2))
        tmp.replace(root / 'result.json')

    save()
    try:
        rows = collect(cfg, checkpoint, scenarios, 119000)
        torch.save(rows, root / 'dataset.pt')
        split = max(1, scenarios * 3 // 4)
        train = [r for r in rows if r['scenario'] < split]
        test = [r for r in rows if r['scenario'] >= split]
        if not train or not test:
            raise ValueError('need nonempty disjoint scenario splits')
        samples = transitions(train, 0)
        groups = {y: [t for t in samples if t.G == y] for y in (-1, 1)}
        if not all(groups.values()):
            raise ValueError('both positive and negative labels required; constant +1 fit is uninformative')
        agent = builder(cfg, checkpoint)(119000)
        panels = {
            'train': (train, 0),
            'train_shuffled': (train, 1),
            'heldout': (test, 0),
            'heldout_shuffled': (test, 1),
        }
        result.update(
            status='fitting',
            split_scenario=split,
            counts={name: dict(Counter(t.G for t in transitions(rs, lay))) for name, (rs, lay) in panels.items()},
            before={name: evaluate(agent, rs, lay) for name, (rs, lay) in panels.items()},
        )
        if max(v['max_difference_from_original_online_q'] for v in result['before'].values()) > 1e-4:
            raise ValueError('online and batched Q mismatch; stop fitting')
        save()
        optimizer = torch.optim.AdamW(agent.net.parameters(), lr=0.0003, weight_decay=0)
        rng = random.Random(119001)
        result['curve'] = []
        for step in range(1, steps + 1):
            chosen = [rng.choice(groups[y]) for y in (-1, 1) for _ in range(16)]
            batch, actions, targets = collate_batch(chosen, device='cpu', max_actions=agent.cfg.max_actions)
            q = agent.forward_batch(batch)[0].gather(1, actions[:, None]).squeeze(1)
            loss = ((q - targets) ** 2).mean()
            if not torch.isfinite(loss):
                raise ValueError('nonfinite fit loss')
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            if step in (1, 25, 100, steps):
                result['curve'].append({'step': step, 'train': evaluate(agent, train, 0)})
                print(f'fit step={step} train_mse={result["curve"][-1]["train"]["mse"]:.4f}', flush=True)
        result['after'] = {name: evaluate(agent, rs, lay) for name, (rs, lay) in panels.items()}
        assert hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest() == sha
        torch.save(
            {'net': agent.net.state_dict(), 'diagnostic_only': True, 'source_checkpoint_sha256': sha},
            root / 'diagnostic_weights.pt',
        )
        result.update(status='complete', original_checkpoint_unchanged=True)
        save()
    except BaseException as error:
        result.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('output')
    p.add_argument('--scenarios', type=int, default=8)
    p.add_argument('--steps', type=int, default=400)
    a = p.parse_args()
    run(a.config, a.checkpoint, a.output, a.scenarios, a.steps)
