"""Fresh full-network target learning with balanced conditional states and ablation."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.target_data import ENV, collect
from tools.experiments.tactical_learning import batch_rows
from training.core.artifact_io import provenance, save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.config import DMCParadigmConfig

PROTOCOL = Path('openspec/changes/card-target-learning-v12/protocol.md')


def evaluate(agent, rows, erase_target=False):
    agent.net.eval()
    details = []
    with torch.no_grad():
        for row in rows:
            batch, _ = batch_rows([row], agent.cfg.max_actions)
            if erase_target:
                batch['action_refs'][:, :2, 2] = -1
            logits, _, _ = agent.forward_batch(batch)
            logits = logits[0, :2].numpy()
            ties = logits == logits.max()
            hit = float(np.mean(row['utility'][ties] == row['utility'].max()))
            details.append({k: row[k] for k in ('seed', 'side', 'wounded', 'active')} | {'hit': hit})
    return {
        'hit': float(np.mean([r['hit'] for r in details])),
        'states': details,
        'by_field': {
            k: {str(v): float(np.mean([r['hit'] for r in details if r[k] == v])) for v in (0, 1)}
            for k in ('side', 'wounded', 'active')
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--train-start', type=int, default=400)
    parser.add_argument('--test-start', type=int, default=93000)
    parser.add_argument('--protocol', type=Path, default=PROTOCOL)
    args = parser.parse_args()
    protocol = args.protocol
    train_seeds = list(range(args.train_start, args.train_start + 8))
    test_seeds = list(range(args.test_start, args.test_start + 4))
    if set(train_seeds) & set(test_seeds):
        raise ValueError('train/test seeds overlap')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'protocol.md').write_bytes(protocol.read_bytes())
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    cfg = load_cfg('configs/dmc/readiness_tactics.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    torch.manual_seed(100)
    collector = DmcAgent(shape, epsilon=0)
    train = collect(collector, train_seeds)
    test = collect(collector, test_seeds)
    protocol_hash = hashlib.sha256(protocol.read_bytes()).hexdigest()
    save_checkpoint({'train': train, 'test': test, 'protocol_sha256': protocol_hash}, args.output / 'dataset.pt')
    report = {
        'provenance': provenance(),
        'protocol_sha256': protocol_hash,
        'environment': ENV,
        'train_seeds': train_seeds,
        'test_seeds': test_seeds,
        'train_n': len(train),
        'test_n': len(test),
        'results': [],
    }
    for seed in (41, 42, 43):
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        agent = DmcAgent(shape, epsilon=0, lr=0.0003)
        row = {'seed': seed, 'before': evaluate(agent, test)}
        agent.net.train()
        losses = []
        for step in range(200):
            selected = [train[i] for i in rng.integers(len(train), size=8)]
            batch, target = batch_rows(selected, shape.max_actions)
            agent.optimizer.zero_grad()
            logits, _, _ = agent.forward_batch(batch)
            mask = torch.as_tensor(batch['legal_mask'])
            loss = -(target * logits.masked_fill(~mask, -1e9).log_softmax(-1)).sum(-1).mean()
            if not torch.isfinite(loss):
                raise AssertionError('nonfinite target learning loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(agent.net.parameters(), 1)
            agent.optimizer.step()
            losses.append(float(loss.detach()))
        row.update(
            after=evaluate(agent, test),
            erased=evaluate(agent, test, True),
            train_after=evaluate(agent, train),
            losses=losses,
        )
        report['results'].append(row)
        save_checkpoint(
            {'net': agent.net.state_dict(), 'protocol_sha256': protocol_hash}, args.output / f'target_{seed}.pt'
        )
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print('TARGET DONE', seed, row['after']['hit'], row['erased']['hit'], flush=True)


if __name__ == '__main__':
    main()
