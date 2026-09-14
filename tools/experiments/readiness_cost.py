"""Stage 3 cost probe; reserved transfer cards are never collected."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.cost_data import collect, predict, tensors
from tools.experiments.cost_learning import fit
from training.core.artifact_io import provenance, save_checkpoint
from training.core.network.buffs import BuffEncoder
from training.core.network.encoder import HookEncoder
from training.core.rule_learning import RuleCostProbe

GROUPS = {'a': ['乘胜追击'], 'b': ['佛跳墙', '荷花酥'], 'combination': ['乘胜追击', '佛跳墙', '荷花酥']}
PROTOCOL = Path('openspec/changes/training-learnability-v11/protocol.md')


def metrics(model, data, means):
    model.eval()
    with torch.no_grad():
        pred = torch.cat(
            [
                predict(model, data, torch.arange(i, min(i + 64, len(data['costs']))))
                for i in range(0, len(data['costs']), 64)
            ]
        )
    costs, kinds = data['costs'], data['action_refs'][:, 0]

    def subset(mask):
        baseline = torch.tensor([means[int(k)] for k in kinds[mask]])
        return dict(
            n=int(mask.sum()),
            mse=float((pred[mask] - costs[mask]).square().mean()),
            rounded_accuracy=float((pred[mask].round() == costs[mask]).float().mean()),
            kind_mean_mse=float((baseline - costs[mask]).square().mean()),
        )

    return {
        'all': subset(torch.ones(len(costs), dtype=torch.bool)),
        'by_kind': {str(int(k)): subset(kinds == k) for k in kinds.unique()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'protocol.md').write_bytes(PROTOCOL.read_bytes())
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    data, inventory = {}, {}
    for split, seeds in [('train', range(100, 108)), ('test', range(91000, 91004))]:
        for group, cards in GROUPS.items():
            if split == 'train' and group == 'combination':
                continue
            name = group + '_' + split
            raw = collect(cards, seeds, args.output / (name + '.npz'))
            data[name] = tensors(raw)
            inventory[name] = {
                'n': len(raw['costs']),
                'seeds': sorted(set(raw['game_seed'].tolist())),
                'cost_counts': {str(k): int(v) for k, v in zip(*np.unique(raw['costs'], return_counts=True))},
            }
            print('COLLECT', name, inventory[name]['n'], flush=True)
    train = [data['a_train'], data['b_train']]
    kinds = torch.cat([d['action_refs'][:, 0] for d in train])
    costs = torch.cat([d['costs'] for d in train])
    means = {int(k): float(costs[kinds == k].mean()) for k in kinds.unique()}
    report = {
        'provenance': provenance(),
        'protocol_sha256': hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        'groups': GROUPS,
        'inventory': inventory,
        'kind_means': means,
        'results': [],
    }
    for seed in (41, 42, 43):
        torch.manual_seed(seed)
        model = RuleCostProbe(HookEncoder(token_dim=16, max_ops=128, dropout=0), BuffEncoder(16), 16)
        row = {'seed': seed, 'before': {g: metrics(model, data[g + '_test'], means) for g in GROUPS}}
        fit(model, train, 150, seed)
        row['after'] = {g: metrics(model, data[g + '_test'], means) for g in GROUPS}
        report['results'].append(row)
        save_checkpoint(
            {'probe': model.state_dict(), 'protocol_sha256': report['protocol_sha256']},
            args.output / f'probe_{seed}.pt',
        )
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print('DONE', seed, {g: row['after'][g]['all'] for g in GROUPS}, flush=True)


if __name__ == '__main__':
    main()
