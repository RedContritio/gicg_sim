"""Matched D2 self-play reference for separating team strength from policy performance."""

import argparse
from pathlib import Path
from tools.experiments.semantic_training.evaluate import evaluate


def run(config, output, workers=24):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    for seed in (147000, 148000, 149000):
        evaluate(
            config,
            'teacher-d2',
            root / str(seed),
            scenarios=120,
            layouts=2,
            workers=workers,
            seed=seed,
            opponent_depth=2,
        )


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('output')
    p.add_argument('--workers', type=int, default=24)
    a = p.parse_args()
    run(a.config, a.output, a.workers)
