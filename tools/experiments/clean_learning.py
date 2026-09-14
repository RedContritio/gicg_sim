"""Fresh three-seed DMC pilot, held-out decks and same-budget fine-tuning.

Run: python -m tools.experiments.clean_learning --output artifacts/clean_learning_v6
This is a bounded pilot, not a convergence or generalization certificate.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from training.core.artifact_io import provenance

ROOT = Path(__file__).resolve().parents[2]


def invoke(argv, log):
    print('RUN', ' '.join(map(str, argv)), flush=True)
    with log.open('w') as out:
        subprocess.run(
            [sys.executable, '-m', *map(str, argv)],
            cwd=ROOT,
            stdout=out,
            stderr=subprocess.STDOUT,
            check=True,
            env={**os.environ, 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'},
        )


def config(path, seed, output, cards, frames):
    path.write_text(f'''[meta]
extends = "{ROOT / 'configs/dmc/smoke.toml'}"
seed = {seed}
run_label = "clean_seed{seed}_{path.stem}"
[scenario]
card_pool = {json.dumps(cards, ensure_ascii=False)}
[paradigm.dmc]
total_frames = {frames}
max_game_steps = 256
epsilon = 0.2
lr = 0.0003
eval_interval_episodes = 0
[checkpoint]
artifacts_root = "{output}"
save_every = 50
keep_last_n = 1
''')


def train(cfg, dest, label, resume=None):
    out = dest / label
    if not (out / 'complete.json').exists():
        invoke(
            ['tools.experiments.train_seeded', cfg, out] + (['--initial', resume] if resume else []),
            dest / f'{label}.log',
        )
    return out / 'ckpts/latest.pt'


def evaluate(cfg, paths, dest, n):
    import tomllib

    raw = tomllib.loads(cfg.read_text())
    eval_cfg = cfg.with_name(cfg.stem + '_eval.toml')
    cards = raw['scenario']['card_pool']
    eval_cfg.write_text(
        'base = "smoke"\nmax_game_steps = 256\n[scenario]\nteam_0 = ["赤蝶"]\n'
        'team_1 = ["墨客"]\nmax_rounds = 5\ncard_pool = '
        + json.dumps(cards, ensure_ascii=False)
        + '\n[agent]\nd_model = 32\nn_cross_layers = 1\n'
    )
    invoke(
        [
            'tools.eval.ckpt',
            eval_cfg,
            '--ckpts',
            *paths,
            '--baselines',
            'random',
            'F1-D2',
            '--n-scenarios',
            n,
            '--scenarios-seed',
            '91000',
            '--output-dir',
            dest,
        ],
        dest.parent / (dest.name + '.log'),
    )
    return json.loads((dest / 'summary.json').read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--frames', type=int, default=5000)
    p.add_argument('--seed', type=int, default=41)
    p.add_argument('--scenarios', type=int, default=16)
    args = p.parse_args()
    dest = args.output.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    report = {
        'provenance': provenance(),
        'frames': args.frames,
        'scenarios': args.scenarios,
        'seeds': [args.seed],
        'protocol': 'paired evaluation seeds; whole card-combination holdout',
        'results': [],
    }
    for seed in report['seeds']:
        cfg = dest / f'base_{seed}.toml'
        held = dest / f'held_{seed}.toml'
        config(cfg, seed, dest, ['测试卡_增幅', '测试卡_碎片'], args.frames)
        config(held, seed, dest, ['乘胜追击', '速速茶点'], args.frames)
        ckpt = train(cfg, dest, f'train_{seed}')
        row = {'seed': seed, 'checkpoint': str(ckpt)}
        row['base'] = evaluate(cfg, [str(ckpt), 'random'], dest / f'base_eval_{seed}', args.scenarios)
        row['zero_shot'] = evaluate(held, [str(ckpt), 'random'], dest / f'held_eval_{seed}', args.scenarios)
        for budget in (250, 1000):
            adapt_cfg = dest / f'adapt_{seed}_{budget}.toml'
            config(adapt_cfg, seed, dest, ['乘胜追击', '速速茶点'], budget)
            adapted = train(adapt_cfg, dest, f'adapt_{seed}_{budget}', resume=str(ckpt))
            row[f'adapt_{budget}'] = evaluate(
                held, [str(adapted)], dest / f'adapt_eval_{seed}_{budget}', args.scenarios
            )
            row[f'retention_{budget}'] = evaluate(
                cfg, [str(adapted)], dest / f'retention_eval_{seed}_{budget}', args.scenarios
            )
        report['results'].append(row)
        (dest / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(dest / 'report.json', flush=True)


if __name__ == '__main__':
    main()
