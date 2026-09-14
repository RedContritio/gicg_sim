"""Fixed eight-card 2v2 curriculum: fresh BC, RL, D2 selection and paired holdout."""

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


def run(config, output, workers=16):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    status = dict(status='running', stage='warmup', config=config, provenance=provenance())

    def save():
        status['wall_s'] = time.monotonic() - start
        tmp = root / 'result.tmp'
        tmp.write_text(json.dumps(status, indent=2), encoding='utf-8')
        tmp.replace(root / 'result.json')

    with tarfile.open(root / 'source.tar.gz', 'w:gz') as archive:
        for directory in ('tools/experiments/semantic_training', 'configs'):
            for path in sorted(Path(directory).rglob('*')):
                if path.suffix in ('.py', '.toml'):
                    archive.add(path, arcname=str(path))
    save()
    try:
        warmup(config, str(root / 'warmup'), episodes=512, steps=4000, workers=workers)
        anchor = json.loads((root / 'warmup/result.json').read_text())['checkpoint']
        status.update(stage='rl', anchor=anchor)
        save()
        train_rl(
            config,
            anchor,
            str(root / 'rl'),
            iterations=8,
            episodes=128,
            workers=workers,
            seed=160000,
            dev_seed=161000,
            dev_scenarios=120,
            batch_size=16,
            dev_depth=2,
        )
        trained = json.loads((root / 'rl/result.json').read_text())
        chosen = max(trained['iterations'], key=lambda row: (row['dev_score'], -row['iteration']))
        candidate = chosen['checkpoint']
        status.update(
            stage='holdout',
            selected=chosen,
            candidate_sha256=hashlib.sha256(Path(candidate).read_bytes()).hexdigest(),
        )
        save()  # Freeze candidate before opening independent final cases.
        for depth in (2, 1):
            for name, checkpoint in [('bc', anchor), ('rl', candidate)]:
                evaluate(config, checkpoint, root / f'{name}_d{depth}', 360, 2, workers, 162000, opponent_depth=depth)
            compare(
                root / f'bc_d{depth}/result.json', root / f'rl_d{depth}/result.json', root / f'paired_d{depth}.json'
            )
        status['stage'] = 'stability'
        save()
        stability(config, candidate, str(root / 'stability.json'), 60, workers, 163000)
        status.update(status='complete', stage='complete', candidate=candidate)
        save()
        print(status, flush=True)
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('output')
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    run(args.config, args.output, args.workers)
