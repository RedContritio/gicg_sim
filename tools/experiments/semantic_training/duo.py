"""Five-character 2v2 RL and independent D1/D2 acceptance panels."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time

from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.rl import run as train_rl
from tools.experiments.semantic_training.stability import run as stability
from tools.experiments.semantic_training.compare import compare
from training.core.artifact_io import provenance, load_checkpoint


def run(config, warmup, output, workers=16):
    warm = json.loads((Path(warmup) / 'result.json').read_text())
    if warm['status'] != 'complete':
        raise ValueError('warm-up must be complete')
    anchor = warm['checkpoint']
    load_checkpoint(anchor, map_location='cpu', weights_only=False)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    status = {'status': 'running', 'stage': 'baseline', 'anchor': anchor, 'provenance': provenance()}

    def save():
        status['wall_s'] = time.monotonic() - start
        temp = root / 'result.tmp'
        temp.write_text(json.dumps(status, indent=2), encoding='utf-8')
        temp.replace(root / 'result.json')

    with tarfile.open(root / 'experiment_source.tar.gz', 'w:gz') as tar:
        for directory in ('tools/experiments/semantic_training', 'configs'):
            for path in sorted(Path(directory).rglob('*')):
                if path.suffix in ('.py', '.toml'):
                    tar.add(path, arcname=str(path))
    save()
    try:
        evaluate(config, anchor, root / 'bc_dev', 60, 2, workers, 141000)
        status['stage'] = 'rl'
        save()
        train_rl(
            config,
            anchor,
            str(root / 'rl'),
            iterations=8,
            episodes=128,
            workers=workers,
            seed=140000,
            dev_seed=141000,
            dev_scenarios=60,
            batch_size=16,
        )
        trained = json.loads((root / 'rl/result.json').read_text())
        chosen = max(trained['iterations'], key=lambda row: (row['dev_score'], -row['iteration']))
        candidate = chosen['checkpoint']
        status.update(
            stage='independent_evaluation',
            selected=chosen,
            candidate_sha256=hashlib.sha256(Path(candidate).read_bytes()).hexdigest(),
        )
        save()  # Freeze choice before opening any final panel.
        for depth in (1, 2):
            for name, checkpoint in [('bc', anchor), ('rl', candidate)]:
                evaluate(config, checkpoint, root / f'{name}_d{depth}', 240, 4, workers, 142000, opponent_depth=depth)
            compare(
                root / f'bc_d{depth}/result.json', root / f'rl_d{depth}/result.json', root / f'paired_d{depth}.json'
            )
        evaluate(config, 'teacher-d2', root / 'teacher_d1', 240, 4, workers, 142000)
        status['stage'] = 'layout_stability'
        save()
        stability(config, candidate, str(root / 'stability.json'), 60, workers, 143000)
        panels = {
            name: json.loads((root / name / 'result.json').read_text())
            for name in ('bc_d1', 'rl_d1', 'bc_d2', 'rl_d2', 'teacher_d1')
        }
        status.update(
            status='complete',
            stage='complete',
            scores={
                name: {
                    k: panel[k]
                    for k in (
                        'score',
                        'cluster_bootstrap95',
                        'wins',
                        'draws',
                        'timeout_games',
                        'timeout_wins',
                        'per_matchup',
                        'per_layout',
                    )
                }
                for name, panel in panels.items()
            },
        )
        status['d1_significantly_beaten'] = panels['rl_d1']['cluster_bootstrap95'][0] > 0.5
        save()
        print(status, flush=True)
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('warmup')
    parser.add_argument('output')
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    run(args.config, args.warmup, args.output, args.workers)
