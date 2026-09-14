"""Supplemental uncapped D3 panel for the frozen 2v2 BC/RL candidates."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.teams import eval_cases
from tools.experiments.semantic_training.compare import compare
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg


def run(config, anchor, candidate, output, workers=8):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    seed, n = 150000, 120
    cases = eval_cases(load_cfg(config), seed, n)
    jobs = [(i, side, 0, case, seed) for i, case in enumerate(cases) for side in (0, 1)]
    for name, path in [('bc', anchor), ('rl', candidate)]:
        start = time.monotonic()
        result = dict(
            status='running',
            seed=seed,
            scenarios=n,
            layouts=1,
            opponent_depth=3,
            checkpoint=path,
            checkpoint_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            provenance=provenance(),
            games=[],
        )

        def save():
            result['wall_s'] = time.monotonic() - start
            (root / f'{name}.tmp').write_text(json.dumps(result, indent=2), encoding='utf-8')
            (root / f'{name}.tmp').replace(root / f'{name}.json')

        save()
        try:
            with ProcessPoolExecutor(
                max_workers=workers, initializer=ev.initialize, initargs=(config, path, 3)
            ) as pool:
                for row in pool.map(ev.game, jobs):
                    result['games'].append(row)
                    if len(result['games']) % 30 == 0:
                        save()
                        print(name, len(result['games']), flush=True)
            scores = np.array([r['score'] for r in result['games']]).reshape(n, 2).mean(axis=1)
            draws = np.random.default_rng(seed).integers(n, size=(10000, n))
            result.update(
                status='complete',
                score=float(scores.mean()),
                per_layout=[float(scores.mean())],
                cluster_bootstrap95=np.quantile(scores[draws].mean(axis=1), [0.025, 0.975]).tolist(),
            )
            save()
        except BaseException as error:
            result.update(status='failed', error=repr(error))
            save()
            raise
    compare(root / 'bc.json', root / 'rl.json', root / 'paired.json')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('anchor')
    p.add_argument('candidate')
    p.add_argument('output')
    p.add_argument('--workers', type=int, default=8)
    a = p.parse_args()
    run(a.config, a.anchor, a.candidate, a.output, a.workers)
