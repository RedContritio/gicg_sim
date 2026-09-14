"""Controlled vocabulary-extension test, NOT an engine-mechanic extension.

Re-encode existing OpBinOp/BinSub as a new dedicated SUB opcode 16. The
operation is semantically identical; labels remain actual engine payments.
This isolates adding an embedding row and learning the new representation.
"""

import argparse
import copy
import json
from pathlib import Path

import torch

from tools.experiments.cost_data import tensors
from tools.experiments.cost_learning import fit, score
from training.core.artifact_io import load_checkpoint, load_dataset, provenance, save_checkpoint, save_dataset
from training.core.network.adaptation import load_for_adaptation
from training.core.network.buffs import BuffEncoder
from training.core.network.encoder import HookEncoder
from training.core.rule_learning import RuleCostProbe


def read(path, expand=False):
    with load_dataset(path, allow_pickle=False) as source:
        raw = {k: source[k].copy() for k in ('hook_ir', 'buffs', 'action_refs', 'costs')}
    ir = raw['hook_ir']
    selected = (ir[:, :, 0] == 5) & (ir[:, :, 2] == 2)
    if expand:
        if not selected.any():
            raise ValueError('no subtraction instructions; experiment would not exercise the new token')
        ir[:, :, 0][selected] = 16
    return raw, int(selected.sum())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    raw_train, count = read(args.source / 'combination_train.npz', True)
    raw_test, _ = read(args.source / 'combination_test.npz', True)
    save_dataset(args.output / 'expanded_train.npz', **raw_train)
    save_dataset(args.output / 'expanded_test.npz', **raw_test)
    train, test = tensors(raw_train), tensors(raw_test)
    original_train = tensors(read(args.source / 'combination_train.npz')[0])
    original_test = tensors(read(args.source / 'combination_test.npz')[0])
    old = tensors(read(args.source / 'a_train.npz')[0])
    retention = tensors(read(args.source / 'a_test.npz')[0])
    mean = old['costs'].mean()
    report = {
        'provenance': provenance(),
        'kind': 'representation-only SUB primitive extension',
        'engine_new_mechanic': False,
        'rewritten_instructions': count,
        'results': [],
    }
    for seed in (41, 42, 43):
        torch.manual_seed(seed)
        model = RuleCostProbe(HookEncoder(opcode_vocab=17, token_dim=16, max_ops=128, dropout=0), BuffEncoder(16), 16)
        base = load_checkpoint(args.source / f'base_{seed}.pt', weights_only=True)['probe']
        changed = load_for_adaptation(model, base)
        assert changed == ['hook_encoder.opcode_embed.weight']
        row = {'seed': seed, 'zero_shot': score(model, test, mean)}
        for samples in (16, 64):
            adapted = copy.deepcopy(model)
            subset = dict(train)
            for name in ('buffs', 'action_refs', 'costs'):
                subset[name] = subset[name][:samples]
            before = adapted.hook_encoder.opcode_embed.weight[16].detach().clone()
            fit(adapted, [subset, old], 60, seed)
            delta = float((adapted.hook_encoder.opcode_embed.weight[16].detach() - before).norm())
            assert delta > 0
            row[str(samples)] = {
                'target': score(adapted, test, mean),
                'retention': score(adapted, retention, mean),
                'new_row_delta_norm': delta,
            }
            save_checkpoint({'probe': adapted.state_dict()}, args.output / f'adapt_{seed}_{samples}.pt')
            control = RuleCostProbe(
                HookEncoder(opcode_vocab=16, token_dim=16, max_ops=128, dropout=0), BuffEncoder(16), 16
            )
            control.load_state_dict(base)
            original_subset = dict(original_train)
            for name in ('buffs', 'action_refs', 'costs'):
                original_subset[name] = original_subset[name][:samples]
            fit(control, [original_subset, old], 60, seed)
            row[str(samples)]['unchanged_representation_control'] = score(control, original_test, mean)

        report['results'].append(row)
        (args.output / 'report.json').write_text(json.dumps(report, indent=2))
        print('DONE', seed, flush=True)


if __name__ == '__main__':
    main()
