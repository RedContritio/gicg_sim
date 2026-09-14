"""Resume the interrupted L6 update, preserving completed rounds and protocol."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time

import torch

from tools.experiments.semantic_training.curriculum import finish, read
from tools.experiments.semantic_training.rl import run as train_rl
from training.core.artifact_io import load_checkpoint, provenance


def merge_iterations(before, after, total):
    rows = before + after
    if [row['iteration'] for row in rows] != list(range(1, total + 1)):
        raise ValueError('missing, repeated or reordered training rounds')
    chosen = max(rows, key=lambda row: (row['dev_score'], -row['iteration']))
    return rows, chosen


def run(directory):
    root = Path(directory)
    original = (root / 'result.json').read_text(encoding='utf-8')
    status = json.loads(original)
    if status['status'] != 'failed' or status['stage'] != 'l6_rl':
        raise ValueError('this recovery requires the failed L6 RL stage')
    if [s['level'] for s in status['stages']] != [3, 4, 5] or status['final']:
        raise ValueError('unexpected curriculum progress')
    if provenance()['source_observation_sha256'] != status['provenance']['source_observation_sha256']:
        raise ValueError('environment changed since interrupted training')
    old = json.loads((root / 'l6/rl/result.json').read_text(encoding='utf-8'))
    checkpoint = Path(old['run']) / 'ckpts/latest.pt'
    payload = load_checkpoint(checkpoint, map_location='cpu', weights_only=False)
    if old['status'] != 'failed' or payload['iteration'] != old['iterations'][-1]['iteration']:
        raise ValueError('latest checkpoint does not match the last fully evaluated round')
    # A new CUDA context must work before changing the master status to running.
    tensor = torch.randn(1024, 1024, device='cuda')
    product = tensor @ tensor
    product.argsort(dim=1, stable=True)
    torch.cuda.synchronize()
    if not torch.isfinite(product).all():
        raise ValueError('CUDA health probe returned nonfinite values')
    del tensor, product
    torch.cuda.empty_cache()
    print(
        {'cuda': torch.cuda.get_device_name(), 'resume_iteration': payload['iteration'], 'checkpoint': str(checkpoint)},
        flush=True,
    )
    del payload
    recovery = root / 'recovery_1'
    recovery.mkdir(exist_ok=False)
    (recovery / 'failed_master.json').write_text(original, encoding='utf-8')
    with tarfile.open(recovery / 'source.tar.gz', 'w:gz') as archive:
        for path in sorted(Path('tools/experiments/semantic_training').glob('*.py')):
            archive.add(path)
    start, prior_wall = time.monotonic(), status['wall_s']
    settings, budgets = old['settings'], status['budgets']
    status.update(
        status='running',
        stage='l6_rl_recovery',
        recovery=dict(
            resume_checkpoint=str(checkpoint),
            sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            original_failure='recovery_1/failed_master.json',
        ),
    )
    status.pop('error', None)

    def save():
        status['wall_s'] = prior_wall + time.monotonic() - start
        temp = root / 'result.tmp'
        temp.write_text(json.dumps(status, indent=2), encoding='utf-8')
        temp.replace(root / 'result.json')

    save()
    try:
        output = root / 'l6/rl_recovery_1'
        train_rl(
            'configs/dmc/curriculum_l6.toml',
            old['anchor'],
            str(output),
            iterations=budgets['rl_iterations'],
            episodes=settings['episodes'],
            workers=budgets['workers'],
            resume=str(checkpoint),
            seed=settings['master_seed'],
            dev_seed=settings['dev_seed'],
            dev_scenarios=settings['dev_scenarios'],
            batch_size=settings['batch_size'],
            dev_depth=settings['dev_depth'],
            opponent_depth=settings['opponent_depth'],
        )
        resumed = read(output / 'result.json')
        rows, chosen = merge_iterations(old['iterations'], resumed['iterations'], budgets['rl_iterations'])
        combined = dict(
            status='complete', iterations=rows, sources=['l6/rl/result.json', 'l6/rl_recovery_1/result.json']
        )
        (recovery / 'combined_l6_rl.json').write_text(json.dumps(combined, indent=2), encoding='utf-8')
        warm = read(root / 'l6/warmup/result.json')
        bc_score = read(root / 'l6/bc_dev/result.json')['score']
        previous = chosen['checkpoint'] if chosen['dev_score'] > bc_score else old['anchor']
        status['stages'].append(
            dict(
                level=6,
                anchor=old['anchor'],
                candidate=chosen['checkpoint'],
                transfer=previous,
                bc_dev=bc_score,
                rl_dev=chosen['dev_score'],
                deck_counts=warm['deck_counts'],
                rl_results='recovery_1/combined_l6_rl.json',
            )
        )
        save()
        print(status['stages'][-1], flush=True)
        finish(root, status, previous, budgets['workers'], budgets['rl_iterations'], budgets['rl_episodes'], save)
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    run(parser.parse_args().directory)
