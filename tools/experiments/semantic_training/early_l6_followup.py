"""Audit BC and all frozen final policies after the primary acceptance audits."""

import argparse
import json
from pathlib import Path
import time

from tools.experiments.semantic_training.early_l6 import run as audit


def run(directory, workers=8):
    root = Path(directory)
    deadline = time.monotonic() + 86400
    while True:
        status = json.loads((root / 'result.json').read_text(encoding='utf-8'))
        if status['status'] == 'failed':
            raise RuntimeError(f'primary curriculum failed: {status.get("error")}')
        finalization = root / 'finalization.json'
        if finalization.exists() and json.loads(finalization.read_text(encoding='utf-8'))['status'] == 'complete':
            break
        if time.monotonic() > deadline:
            raise TimeoutError('primary acceptance audits did not complete')
        time.sleep(30)
    targets = [('bc', status['stages'][-1]['anchor'])]
    targets += [(str(item['seed']), item['candidate']) for item in status['final']]
    for label, checkpoint in targets:
        destination = root / f'early_l6_{label}'
        audit('configs/dmc/curriculum_l6.toml', checkpoint, destination, workers=workers)
    print({'status': 'complete', 'audited': [label for label, _ in targets]}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    run(args.directory, args.workers)
