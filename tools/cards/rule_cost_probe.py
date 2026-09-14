"""Engine-labelled cost examples and a small supervised rule-encoder probe.

python -m tools.cards.rule_cost_probe collect /tmp/old.npz --cards 乘胜追击 速速茶点
python -m tools.cards.rule_cost_probe fit --old old.npz --new new.npz --held-out held.npz --output probe.pt
"""

from training.core.artifact_io import load_dataset, save_checkpoint, save_dataset

import argparse
import hashlib
from pathlib import Path

import numpy as np
import torch

from gicg_env import GicgEnv
from gicg_env._constants import OBS_CHAR_ELEMENT_SLOTS, OBS_CHAR_SKILL_REFS_SIZE, OBS_COUNTER_SLOTS
from training.core.network.buffs import BuffEncoder
from training.core.network.encoder import HookEncoder
from training.core.rule_learning import RuleCostProbe, mixed_indices
from training.core.step_encoding import parse_buffs_np, pad_buffs_np


def collect(args):
    rng = np.random.default_rng(args.seed)
    env = GicgEnv(
        ['赤蝶', '墨客'],
        ['墨客', '赤蝶'],
        card_pool=args.cards,
        pool=['v_legacy', 'test_basic'],
        data_dir='data',
        seed=args.seed,
        max_rounds=8,
    )
    examples = []
    try:
        env.reset(seed=args.seed)
        static = env._static_obs
        start = OBS_COUNTER_SLOTS * 3 + OBS_CHAR_SKILL_REFS_SIZE
        ir = static[start:-OBS_CHAR_ELEMENT_SLOTS].reshape(-1, 128, 5)
        ir = ir[(ir[:, :, 0] != 0).any(-1)]
        for _ in range(args.steps):
            if env.done:
                break
            refs = np.asarray(env.get_action_refs())
            if not len(refs):
                raise RuntimeError('no legal actions at nonterminal state')
            index = int(rng.integers(len(refs)))
            if not env._engine.has_pending:
                payments = np.asarray(env.get_legal_action_payments())
                buffs = parse_buffs_np(env._get_obs(), OBS_COUNTER_SLOTS)
                examples.append((buffs, refs[index], float(payments[index].sum())))
            env.step(index)
        if not examples:
            raise RuntimeError('no decision examples collected')
        # A rule-combination key excludes seeds and observed steps.
        group = hashlib.sha256(
            static.tobytes() + ('v_legacy,test_basic|' + '|'.join(sorted(args.cards))).encode()
        ).hexdigest()
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        save_dataset(
            args.output,
            schema=1,
            group=group,
            hook_ir=ir,
            buffs=pad_buffs_np([x[0] for x in examples]),
            action_refs=np.stack([x[1] for x in examples]),
            costs=np.asarray([x[2] for x in examples], dtype=np.float32),
        )
        active = sum(bool(x[0][:, 0].any()) for x in examples)
        print(f'{len(examples)} examples, {active} with live buffs; group={group}')
    finally:
        env.close()


def load_data(paths):
    datasets = []
    for path in paths:
        with load_dataset(path, allow_pickle=False) as data:
            if int(data['schema']) != 1:
                raise ValueError('unsupported rule example schema')
            datasets.append({k: data[k].copy() for k in data.files})
    return datasets


def sample_loss(probe, dataset, index):
    ir = torch.as_tensor(dataset['hook_ir'], dtype=torch.long).unsqueeze(0)
    mask = torch.ones(ir.shape[:2], dtype=torch.bool)
    buffs = torch.as_tensor(dataset['buffs'][index : index + 1], dtype=torch.float32)
    refs = torch.as_tensor(dataset['action_refs'][index : index + 1], dtype=torch.long)
    target = torch.as_tensor(dataset['costs'][index : index + 1], dtype=torch.float32)
    return (probe(ir, mask, buffs, refs) - target).square().mean()


def fit(args):
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    old, new, held = map(load_data, (args.old, args.new, args.held_out))
    train_groups = {str(d['group']) for d in old + new}
    if train_groups & {str(d['group']) for d in held}:
        raise ValueError('held-out rule combinations overlap training data')
    groups = [old, new]
    locations = [[(d, i) for d in ds for i in range(len(d['costs']))] for ds in groups]
    hook = HookEncoder(token_dim=args.dim, max_ops=128, dropout=0)
    buff = BuffEncoder(args.dim)
    probe = RuleCostProbe(hook, buff, args.dim)
    optimizer = torch.optim.Adam(probe.parameters(), lr=args.lr)
    for _ in range(args.steps):
        probe.train()
        optimizer.zero_grad()
        for source, index in mixed_indices(
            len(locations[0]), len(locations[1]), args.batch_size, args.new_fraction, rng
        ):
            data, row = locations[source][index]
            (sample_loss(probe, data, row) / args.batch_size).backward()
        optimizer.step()
    probe.eval()
    with torch.no_grad():
        for label, datasets in [('old', old), ('new', new), ('held-out', held)]:
            losses = [float(sample_loss(probe, d, i)) for d in datasets for i in range(len(d['costs']))]
            print(f'{label}: n={len(losses)} cost_mse={np.mean(losses):.6f}')
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    save_checkpoint(
        {
            'schema': 1,
            'd_model': args.dim,
            'probe_state_dict': probe.state_dict(),
            'hook_encoder': hook.state_dict(),
            'buff_encoder': buff.state_dict(),
        },
        args.output,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    collect_parser = sub.add_parser('collect')
    collect_parser.add_argument('output')
    collect_parser.add_argument('--cards', nargs='+', required=True)
    collect_parser.add_argument('--steps', type=int, default=100)
    collect_parser.add_argument('--seed', type=int, default=42)
    fit_parser = sub.add_parser('fit')
    for name in ('old', 'new', 'held-out'):
        fit_parser.add_argument('--' + name, nargs='+', required=True)
    fit_parser.add_argument('--output', required=True)
    fit_parser.add_argument('--steps', type=int, default=100)
    fit_parser.add_argument('--batch-size', type=int, default=8)
    fit_parser.add_argument('--new-fraction', type=float, default=0.5)
    fit_parser.add_argument('--dim', type=int, default=32)
    fit_parser.add_argument('--lr', type=float, default=0.001)
    fit_parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if args.steps <= 0:
        parser.error('--steps must be positive')
    (collect if args.command == 'collect' else fit)(args)


if __name__ == '__main__':
    main()
