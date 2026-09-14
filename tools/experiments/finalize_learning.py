"""Authoritative pilot results; recompute all scores with the audited evaluator."""

import argparse
import json
import time
from pathlib import Path

import torch

from tools.experiments.evaluate_clean import evaluate
from tools.experiments.train_seeded import SeededParadigm
from training.core.artifact_io import provenance, save_checkpoint
from training.core.config.loader import load_cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    seed, root = args.seed, args.root
    base = root / f'base_{seed}.toml'
    held = root / f'held_{seed}.toml'
    torch.manual_seed(seed)
    initial = SeededParadigm(seed, None).make_network(load_cfg(base))
    initial_path = root / 'initial/ckpts/latest.pt'
    initial_path.parent.mkdir(parents=True, exist_ok=True)
    save_checkpoint({'net': initial.state_dict(), 'initialization_seed': seed}, initial_path)
    tasks = [
        ('random_base', base, 'random'),
        ('random_held', held, 'random'),
        ('initial_base', base, initial_path),
        ('trained_base', base, root / f'train_{seed}/ckpts/latest.pt'),
        ('zero_shot', held, root / f'train_{seed}/ckpts/latest.pt'),
    ]
    for budget in (250, 1000):
        ckpt = root / f'adapt_{seed}_{budget}/ckpts/latest.pt'
        tasks.extend([(f'adapt_{budget}', held, ckpt), (f'retention_{budget}', base, ckpt)])
    tasks.append(('scratch_1000', held, root / f'scratch_{seed}_1000/ckpts/latest.pt'))
    report = {'provenance': provenance(), 'seed': seed, 'scenarios': 16, 'scenario_seed': 91000, 'results': {}}
    for name, cfg, checkpoint in tasks:
        if isinstance(checkpoint, Path) and name != 'initial_base':
            deadline = time.monotonic() + 600
            while not (checkpoint.parent.parent / 'complete.json').exists():
                if time.monotonic() > deadline:
                    raise TimeoutError(f'training incomplete: {checkpoint}')
                time.sleep(1)
        report['results'][name] = evaluate(cfg, str(checkpoint), 16)
        (root / 'final_evaluation.json').write_text(json.dumps(report, indent=2))
        print(seed, name, flush=True)


if __name__ == '__main__':
    main()
