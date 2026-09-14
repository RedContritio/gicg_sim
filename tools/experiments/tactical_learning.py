"""Fixed-budget full-network imitation of engine-labelled one-step decisions."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.readiness_cost import PROTOCOL
from tools.experiments.tactical_data import collect
from training.core.artifact_io import provenance, save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc._episode import collate_batch
from training.paradigms.dmc.buffer import DmcTransition
from training.paradigms.dmc.config import DMCParadigmConfig


def batch_rows(rows, max_actions):
    batch, _, _ = collate_batch([DmcTransition(r['obs'], 0, 0) for r in rows], 'cpu', max_actions=max_actions)
    target = torch.zeros((len(rows), max_actions))
    for i, row in enumerate(rows):
        best = row['utility'] == row['utility'].max()
        target[i, : len(best)] = torch.as_tensor(best / best.sum())
    return batch, target


def kind_means(rows):
    totals = {}
    for row in rows:
        for kind, value in zip(row['obs']['action_refs'][:, 0], row['utility']):
            totals.setdefault(int(kind), []).append(float(value))
    return {k: float(np.mean(v)) for k, v in totals.items()}


def evaluate(agent, rows, means):
    agent.net.eval()
    details = []
    with torch.no_grad():
        for row in rows:
            values = row['utility']
            if np.ptp(values) == 0:
                continue
            batch, _ = batch_rows([row], agent.cfg.max_actions)
            logits, _, _ = agent.forward_batch(batch)
            index = int(logits[0, : len(values)].argmax())
            kinds = row['obs']['action_refs'][:, 0]
            baseline = np.array([means.get(int(k), 0.0) for k in kinds])
            # Average ties to avoid exploiting legal action ordering.
            tied = baseline == baseline.max()
            best = values.max()
            details.append(
                {
                    'seed': row['seed'],
                    'step': row['step'],
                    'chosen': index,
                    'hit': float(values[index] == best),
                    'regret': float(best - values[index]),
                    'random_hit': float(np.mean(values == best)),
                    'random_regret': float(best - values.mean()),
                    'kind_hit': float(np.mean(values[tied] == best)),
                    'kind_regret': float(best - values[tied].mean()),
                }
            )
    if not details:
        raise ValueError('no nontrivial tactical examples')
    keys = ('hit', 'regret', 'random_hit', 'random_regret', 'kind_hit', 'kind_regret')
    return {
        'n': len(details),
        'ties_only': len(rows) - len(details),
        'mean': {k: float(np.mean([r[k] for r in details])) for k in keys},
        'states': details,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'protocol.md').write_bytes(PROTOCOL.read_bytes())
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    torch.manual_seed(100)
    collector = DmcAgent(shape, epsilon=0)
    train, train_games = collect(cfg, collector, range(200, 208))
    test, test_games = collect(cfg, collector, range(92000, 92004))
    if {r['seed'] for r in train} & {r['seed'] for r in test}:
        raise AssertionError('train/test seed overlap')
    protocol_hash = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    save_checkpoint({'train': train, 'test': test, 'protocol_sha256': protocol_hash}, args.output / 'dataset.pt')
    means = kind_means(train)
    report = {
        'provenance': provenance(),
        'protocol_sha256': protocol_hash,
        'config': asdict(cfg),
        'train_games': train_games,
        'test_games': test_games,
        'kind_means': means,
        'results': [],
    }
    for seed in (41, 42, 43):
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        agent = DmcAgent(shape, epsilon=0, lr=0.0003)
        row = {'seed': seed, 'before': evaluate(agent, test, means)}
        agent.net.train()
        losses = []
        for step in range(100):
            sampled = [train[i] for i in rng.integers(len(train), size=4)]
            batch, target = batch_rows(sampled, shape.max_actions)
            agent.optimizer.zero_grad()
            logits, _, _ = agent.forward_batch(batch)
            # Only legal entries contribute; padded -inf must never multiply zero.
            mask = torch.as_tensor(batch['legal_mask'])
            logprob = logits.masked_fill(~mask, -1e9).log_softmax(-1)
            loss = -(target * logprob).sum(-1).mean()
            if not torch.isfinite(loss):
                raise AssertionError('nonfinite tactical loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(agent.net.parameters(), 1.0)
            agent.optimizer.step()
            losses.append(float(loss.detach()))
        row['losses'] = losses
        row['after'] = evaluate(agent, test, means)
        row['train_after'] = evaluate(agent, train, means)
        report['results'].append(row)
        save_checkpoint(
            {'net': agent.net.state_dict(), 'protocol_sha256': protocol_hash}, args.output / f'tactics_{seed}.pt'
        )
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print('TACTICS DONE', seed, row['after']['mean'], flush=True)


if __name__ == '__main__':
    main()
