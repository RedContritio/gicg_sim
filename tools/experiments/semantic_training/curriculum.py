"""Progressive L3-L6 random-deck training with frozen independent final panels."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time

from tools.experiments.semantic_training.train import run as warmup
from tools.experiments.semantic_training.rl import run as train_rl
from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.compare import compare
from tools.experiments.semantic_training.stability import run as stability
from training.core.artifact_io import provenance


def read(path):
    result = json.loads(Path(path).read_text())
    if result['status'] != 'complete':
        raise ValueError(f'incomplete prerequisite: {path}')
    return result


def run(output, workers=16, teacher_episodes=1024, bc_steps=8000, rl_iterations=12, rl_episodes=256):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    status = dict(status='running', stage='initializing', provenance=provenance(), stages=[], final=[])
    status['budgets'] = dict(
        workers=workers,
        teacher_episodes=teacher_episodes,
        bc_steps=bc_steps,
        rl_iterations=rl_iterations,
        rl_episodes=rl_episodes,
    )

    def save():
        status['wall_s'] = time.monotonic() - start
        temporary = root / 'result.tmp'
        temporary.write_text(json.dumps(status, indent=2), encoding='utf-8')
        temporary.replace(root / 'result.json')

    with tarfile.open(root / 'source.tar.gz', 'w:gz') as archive:
        for directory in (
            'tools/experiments/semantic_training',
            'training',
            'configs',
            'data',
            'gicg_engine',
            'gicg_env',
        ):
            for path in sorted(Path(directory).rglob('*')):
                if path.suffix in ('.py', '.go', '.toml', '.lua'):
                    archive.add(path, arcname=str(path))
    save()
    previous = None
    try:
        for level in (3, 4, 5, 6):
            config = f'configs/dmc/curriculum_l{level}.toml'
            stage = root / f'l{level}'
            stage.mkdir()
            seed = 180000 + level * 10000
            status.update(stage=f'l{level}_bc')
            save()
            warmup(config, str(stage / 'warmup'), teacher_episodes, bc_steps, workers, seed, previous)
            warm = read(stage / 'warmup/result.json')
            anchor = warm['checkpoint']
            evaluate(config, anchor, stage / 'bc_dev', 120, 2, workers, seed + 1000, opponent_depth=2)
            status['stage'] = f'l{level}_rl'
            save()
            train_rl(
                config,
                anchor,
                str(stage / 'rl'),
                iterations=rl_iterations,
                episodes=rl_episodes,
                workers=workers,
                seed=seed + 2000,
                dev_seed=seed + 1000,
                dev_scenarios=120,
                batch_size=16,
                dev_depth=2,
                opponent_depth=2,
            )
            trained = read(stage / 'rl/result.json')
            chosen = max(trained['iterations'], key=lambda row: (row['dev_score'], -row['iteration']))
            bc_dev = read(stage / 'bc_dev/result.json')['score']
            # All curriculum transfer choices use development cases only.
            previous = chosen['checkpoint'] if chosen['dev_score'] > bc_dev else anchor
            item = dict(
                level=level,
                anchor=anchor,
                candidate=chosen['checkpoint'],
                transfer=previous,
                bc_dev=bc_dev,
                rl_dev=chosen['dev_score'],
                deck_counts=warm['deck_counts'],
            )
            status['stages'].append(item)
            save()
            print(item, flush=True)
        finish(root, status, previous, workers, rl_iterations, rl_episodes, save)
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        save()
        raise


def finish(root, status, previous, workers, rl_iterations, rl_episodes, save):
    # Three independent RL seeds from the final curriculum transfer policy.
    # No final test cases are opened until every candidate is frozen.
    config = 'configs/dmc/curriculum_l6.toml'
    status.update(stage='final_training', final_anchor=previous)
    save()
    for seed in (271000, 281000, 291000):
        directory = root / f'final_{seed}'
        train_rl(
            config,
            previous,
            str(directory),
            iterations=rl_iterations * 2,
            episodes=rl_episodes,
            workers=workers,
            seed=seed,
            dev_seed=seed + 1000,
            dev_scenarios=240,
            batch_size=16,
            dev_depth=2,
            opponent_depth=2,
        )
        chosen = max(
            read(directory / 'result.json')['iterations'], key=lambda row: (row['dev_score'], -row['iteration'])
        )
        candidate = chosen['checkpoint']
        status['final'].append(
            dict(
                seed=seed,
                candidate=candidate,
                selected=chosen,
                sha256=hashlib.sha256(Path(candidate).read_bytes()).hexdigest(),
            )
        )
        save()
    status['stage'] = 'independent_evaluation'
    save()
    for item in status['final']:
        seed = item['seed'] + 3000
        directory = root / f'acceptance_{item["seed"]}'
        directory.mkdir()
        item['scores'] = {}
        for depth in (1, 2):
            for name, checkpoint in [('anchor', previous), ('rl', item['candidate'])]:
                evaluate(
                    config, checkpoint, directory / f'{name}_d{depth}', 720, 2, workers, seed, opponent_depth=depth
                )
            compare(
                directory / f'anchor_d{depth}/result.json',
                directory / f'rl_d{depth}/result.json',
                directory / f'paired_d{depth}.json',
            )
            panel = read(directory / f'rl_d{depth}/result.json')
            item['scores'][f'd{depth}'] = {key: panel[key] for key in ('score', 'cluster_bootstrap95')}
        stability(config, item['candidate'], str(directory / 'stability.json'), 60, workers, seed + 1000)
        save()
    status['strength_gate_passed'] = all(
        item['scores'][f'd{depth}']['cluster_bootstrap95'][0] > 0.5 for item in status['final'] for depth in (1, 2)
    )
    status.update(status='complete', stage='complete')
    save()  # Completed experiment is not necessarily an achieved strength goal.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    run(args.output, args.workers)
