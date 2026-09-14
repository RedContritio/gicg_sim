"""Controlled multi-layout fit; physical train/test scenarios remain unchanged."""

import argparse
import hashlib
import json
from pathlib import Path
import random

import torch

from tools.experiments.evaluate_history import builder
from tools.experiments.layout_training.collect import collect
from tools.experiments.terminal_fit.run import evaluate, transitions
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.paradigms.dmc._episode import collate_batch


def run(config, checkpoint, output, steps=400, device='cuda', scenarios=8):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(119000)
    cfg = load_cfg(config)
    sha = hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest()
    result = {
        'status': 'collecting',
        'provenance': provenance(),
        'checkpoint_sha256': sha,
        'steps': steps,
        'device': device,
        'training_layouts': [0, 2, 3],
        'test_layouts': [1, 4],
        'tool_sha256': {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path('tools/experiments/layout_training').glob('*.py')
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
            raise ValueError('empty scenario split')
        samples = [t for layout in result['training_layouts'] for t in transitions(train, layout)]
        groups = {y: [t for t in samples if t.G == y] for y in (-1, 1)}
        if not all(groups.values()):
            raise ValueError('both label signs required')
        agent = builder(cfg, checkpoint)(119000)
        agent.net.to(device)
        agent.device = torch.device(device)
        panels = {
            f'{name}_layout{layout}': (data, layout)
            for name, data in [('train', train), ('heldout', test)]
            for layout in range(5)
        }
        result.update(
            status='fitting',
            split_scenario=split,
            before={name: evaluate(agent, data, layout) for name, (data, layout) in panels.items()},
        )
        assert max(v['max_difference_from_original_online_q'] for v in result['before'].values()) < 1e-4
        save()
        optimizer = torch.optim.AdamW(agent.net.parameters(), lr=0.0003, weight_decay=0)
        rng = random.Random(119001)
        result['curve'] = []
        for step in range(1, steps + 1):
            chosen = [rng.choice(groups[y]) for y in (-1, 1) for _ in range(16)]
            batch, actions, targets = collate_batch(chosen, device=device, max_actions=agent.cfg.max_actions)
            q = agent.forward_batch(batch)[0].gather(1, actions[:, None]).squeeze(1)
            loss = ((q - targets) ** 2).mean()
            if not torch.isfinite(loss):
                raise ValueError('nonfinite loss')
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            if step == 1 or step % 100 == 0 or step == steps:
                result['curve'].append({'step': step, 'sample_loss': float(loss.detach())})
                save()
                print(result['curve'][-1], flush=True)
        result['after'] = {name: evaluate(agent, data, layout) for name, (data, layout) in panels.items()}
        torch.save(
            {
                'net': {k: v.cpu() for k, v in agent.net.state_dict().items()},
                'diagnostic_only': True,
                'source_checkpoint_sha256': sha,
            },
            root / 'diagnostic_weights.pt',
        )
        assert hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest() == sha
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
    p.add_argument('--steps', type=int, default=400)
    p.add_argument('--device', default='cuda')
    p.add_argument('--scenarios', type=int, default=8)
    a = p.parse_args()
    run(a.config, a.checkpoint, a.output, a.steps, a.device, a.scenarios)
