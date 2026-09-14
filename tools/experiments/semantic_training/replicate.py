"""Four fresh RL seeds plus the frozen pilot, with predeclared common holdout."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.stability import run as stability

SEEDS = (132000, 133000, 134000, 135000)


def run(config, anchor, output, pilot):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    plan = dict(
        seeds=list(SEEDS),
        anchor=anchor,
        pilot=pilot,
        parallel_runs=2,
        workers_per_run=12,
        iterations=8,
        episodes=128,
        dev_seed=129000,
        holdout_seed=136000,
        scenarios=256,
        layouts=4,
        selection='highest dev score, earliest iteration on ties',
    )
    (root / 'plan.json').write_text(json.dumps(plan, indent=2))

    def train(seed):
        output = root / f'train_{seed}'
        command = [
            sys.executable,
            '-X',
            'utf8',
            '-u',
            '-m',
            'tools.experiments.semantic_training.rl',
            config,
            anchor,
            str(output),
            '--seed',
            str(seed),
            '--workers',
            '12',
        ]
        with (root / f'train_{seed}.log').open('w', encoding='utf-8') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        print({'trained': seed}, flush=True)
        return output / 'result.json'

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(train, SEEDS))
    selections = []
    for seed, path in [(128000, Path(pilot))] + list(zip(SEEDS, results)):
        result = json.loads(path.read_text())
        if result['status'] != 'complete' or result['settings']['master_seed'] != seed:
            raise ValueError('training result incomplete or wrong seed')
        selected = max(result['iterations'], key=lambda x: (x['dev_score'], -x['iteration']))
        selections.append(
            dict(
                seed=seed,
                checkpoint=selected['checkpoint'],
                iteration=selected['iteration'],
                dev_score=selected['dev_score'],
            )
        )
    # Written before any holdout outcomes are observed. No cross-seed winner selection.
    (root / 'selection.json').write_text(json.dumps(selections, indent=2))
    evaluate(config, anchor, root / 'holdout_bc', 256, 4, 16, 136000)
    for selected in selections:
        seed = selected['seed']
        evaluate(config, selected['checkpoint'], root / f'holdout_{seed}', 256, 4, 16, 136000)
        stability(config, selected['checkpoint'], str(root / f'stability_{seed}.json'), 64, 16, 137000)
    (root / 'complete.json').write_text(json.dumps({'status': 'complete', 'selections': selections}, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('anchor')
    p.add_argument('output')
    p.add_argument('pilot')
    a = p.parse_args()
    run(a.config, a.anchor, a.output, a.pilot)
