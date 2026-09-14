"""Three-seed rule probe: combination holdout, unseen-op exposure and forgetting."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.cost_data import collect, predict, tensors
from training.core.artifact_io import provenance, save_checkpoint
from training.core.network.buffs import BuffEncoder
from training.core.network.encoder import HookEncoder
from training.core.rule_learning import RuleCostProbe


def fit(model, datasets, steps, seed):
    rng = np.random.default_rng(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    model.train()
    for _ in range(steps):
        data = datasets[int(rng.integers(len(datasets)))]
        indices = torch.as_tensor(rng.integers(len(data['costs']), size=32))
        optimizer.zero_grad()
        loss = (predict(model, data, indices) - data['costs'][indices]).square().mean()
        loss.backward()
        optimizer.step()


def score(model, data, mean):
    model.eval()
    errors, rounded = [], []
    with torch.no_grad():
        for start in range(0, len(data['costs']), 64):
            indices = torch.arange(start, min(start + 64, len(data['costs'])))
            pred = predict(model, data, indices)
            target = data['costs'][indices]
            errors.extend((pred - target).square().tolist())
            rounded.extend((pred.round() == target).tolist())
    return {
        'n': len(errors),
        'mse': float(np.mean(errors)),
        'rounded_accuracy': float(np.mean(rounded)),
        'constant_mean_mse': float((data['costs'] - mean).square().mean()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    groups = {
        'a': ['速速茶点'],
        'b': ['乘胜追击'],
        'combination': ['速速茶点', '乘胜追击'],
        'primitive': ['以逸待劳', '荷花酥'],
    }
    raw, data = {}, {}
    for split, seeds in [('train', range(100, 108)), ('test', range(91000, 91004))]:
        for group, cards in groups.items():
            name = group + '_' + split
            raw[name] = collect(cards, seeds, args.output / (name + '.npz'))
            data[name] = tensors(raw[name])
            print('COLLECT', name, len(data[name]['costs']), flush=True)
    old_ops = set(np.concatenate([raw[x + '_train']['hook_ir'][:, :, 0].ravel() for x in ('a', 'b')]))
    new_ops = sorted(set(raw['primitive_train']['hook_ir'][:, :, 0].ravel()) - old_ops)
    mean = torch.cat([data[x + '_train']['costs'] for x in ('a', 'b')]).mean()
    report = {
        'provenance': provenance(),
        'groups': groups,
        'unseen_existing_opcodes': list(map(int, new_ops)),
        'note': 'Engine cost supervision, not game win rate. Primitive means supported opcode absent from base data.',
        'results': [],
    }
    for seed in (41, 42, 43):
        torch.manual_seed(seed)
        model = RuleCostProbe(HookEncoder(token_dim=16, max_ops=128, dropout=0), BuffEncoder(16), 16)
        fit(model, [data['a_train'], data['b_train']], 150, seed)
        row = {'seed': seed, 'base': {g: score(model, data[g + '_test'], mean) for g in groups}}
        save_checkpoint({'probe': model.state_dict()}, args.output / f'base_{seed}.pt')
        for group in ('combination', 'primitive'):
            for count in (16, 64):
                adapted = copy.deepcopy(model)
                subset = dict(data[group + '_train'])
                # Rows kept together by prefix; report unique episode count as well.
                for name in ('costs', 'buffs', 'action_refs'):
                    subset[name] = subset[name][:count]
                fit(adapted, [subset, data['a_train'], data['b_train']], 60, seed)
                row[f'{group}_{count}'] = {
                    'target': score(adapted, data[group + '_test'], mean),
                    'retention_a': score(adapted, data['a_test'], mean),
                    'retention_b': score(adapted, data['b_test'], mean),
                    'unique_games': len(set(raw[group + '_train']['game_seed'][:count].tolist())),
                }
        report['results'].append(row)
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('DONE seed', seed, flush=True)


if __name__ == '__main__':
    main()
