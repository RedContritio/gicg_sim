"""Full public-state encoder auxiliary supervision, without candidate-label leakage."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.rule_state_data import collect
from tools.experiments.tactical_learning import batch_rows
from training.core.artifact_io import provenance, save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.config import DMCParadigmConfig

PROTOCOL = Path('openspec/changes/pre-rl-ready-v14/protocol.md')


def predictions(agent, head, rows):
    features = []
    handle = agent.net.register_forward_hook(
        lambda module, inputs, output: features.append(module.heads['q'].state_proj(output['_state_vec']))
    )
    try:
        batch, _ = batch_rows(rows, agent.cfg.max_actions)
        agent.forward_batch(batch)
        return head(features[-1])
    finally:
        handle.remove()


def evaluate(agent, head, rows):
    agent.net.eval()
    head.eval()
    with torch.no_grad():
        probability = torch.cat(
            [predictions(agent, head, rows[i : i + 8]).sigmoid() for i in range(0, len(rows), 8)]
        ).numpy()
    labels = np.stack([r['labels'] for r in rows])
    pred = probability >= 0.5
    balanced = []
    for j in range(3):
        positive = labels[:, j] == 1
        balanced.append(float((pred[positive, j].mean() + (~pred[~positive, j]).mean()) / 2))
    return {
        'balanced_accuracy': balanced,
        'accuracy': (pred == labels).mean(0).tolist(),
        'majority_accuracy': np.maximum(labels.mean(0), 1 - labels.mean(0)).tolist(),
        'majority_balanced_accuracy': [0.5] * 3,
        # Weighted BCE with positive weight 4 yields q, not calibrated p.
        'cost_mae': float(
            np.mean(
                abs(3 * (1 - probability[:, 0] / (4 - 3 * probability[:, 0])) - np.array([r['cost'] for r in rows]))
            )
        ),
        'probability': probability.tolist(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--train-start', type=int, default=1200)
    parser.add_argument('--test-start', type=int, default=101000)
    parser.add_argument('--steps', type=int, default=600)
    parser.add_argument('--seeds', type=int, nargs='+', choices=(41, 42, 43), default=[41, 42, 43])
    parser.add_argument('--protocol', type=Path, default=Path('openspec/changes/pre-rl-ready-v14/aux-final.md'))
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds):
        parser.error('initialization seeds must be unique')
    if set(range(args.train_start, args.train_start + 4)) & set(range(args.test_start, args.test_start + 2)):
        parser.error('train/test seeds overlap')
    protocol = args.protocol
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'protocol.md').write_bytes(protocol.read_bytes())
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    torch.manual_seed(100)
    collector = DmcAgent(shape, epsilon=0)
    train, test = (
        collect(collector, range(args.train_start, args.train_start + 4)),
        collect(collector, range(args.test_start, args.test_start + 2)),
    )
    protocol_hash = hashlib.sha256(protocol.read_bytes()).hexdigest()
    save_checkpoint({'train': train, 'test': test, 'protocol_sha256': protocol_hash}, args.output / 'dataset.pt')
    labels = torch.as_tensor(np.stack([r['labels'] for r in train]))
    pos_weight = (1 - labels.mean(0)) / labels.mean(0)
    report = {
        'provenance': provenance(),
        'protocol_sha256': protocol_hash,
        'tasks': ['fourth_paid_discount', 'food_target_0', 'food_target_1'],
        'train_n': len(train),
        'test_n': len(test),
        'steps': args.steps,
        'batch_size': 10,
        'sampling': 'two examples per count group 0..4',
        'train_seeds': list(range(args.train_start, args.train_start + 4)),
        'test_seeds': list(range(args.test_start, args.test_start + 2)),
        'results': [],
        'test_cases': [{k: r[k] for k in ('seed', 'side', 'fed', 'count', 'cost', 'trace')} for r in test],
    }
    for seed in args.seeds:
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        agent = DmcAgent(shape, epsilon=0)
        head = torch.nn.Linear(shape.d_model, 3)
        optimizer = torch.optim.AdamW(list(agent.net.parameters()) + list(head.parameters()), lr=0.001)
        row = {'seed': seed, 'before': evaluate(agent, head, test)}
        agent.net.train()
        head.train()
        losses = []
        groups = [[r for r in train if r['count'] == count] for count in range(5)]
        for step in range(args.steps):
            selected = [group[int(rng.integers(len(group)))] for _ in range(2) for group in groups]
            y = torch.as_tensor(np.stack([r['labels'] for r in selected]))
            optimizer.zero_grad()
            logits = predictions(agent, head, selected)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits[:, 0], y[:, 0], pos_weight=pos_weight[0])
            loss = loss + torch.nn.functional.binary_cross_entropy_with_logits(
                logits[:, 1:], y[:, 1:], pos_weight=pos_weight[1:]
            )
            if not torch.isfinite(loss):
                raise AssertionError('nonfinite auxiliary loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(list(agent.net.parameters()) + list(head.parameters()), 1)
            optimizer.step()
            losses.append(float(loss.detach()))
        row.update(after=evaluate(agent, head, test), train_after=evaluate(agent, head, train), losses=losses)
        report['results'].append(row)
        save_checkpoint(
            {'net': agent.net.state_dict(), 'auxiliary_head': head.state_dict(), 'protocol_sha256': protocol_hash},
            args.output / f'aux_{seed}.pt',
        )
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print('AUX DONE', seed, row['after']['balanced_accuracy'], flush=True)


if __name__ == '__main__':
    main()
