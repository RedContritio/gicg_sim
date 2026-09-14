"""Real D2 full-game and observation preflight for every curriculum stage."""

from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from tools.experiments.semantic_training.data import teacher_episode


def run():
    root = Path('artifacts/curriculum_preflight')
    root.mkdir(exist_ok=False)
    results = {}
    for level in (3, 4, 5, 6):
        directory = root / f'l{level}'
        directory.mkdir()
        jobs = [(f'configs/dmc/curriculum_l{level}.toml', i, str(directory), 175000 + level) for i in range(16)]
        with ProcessPoolExecutor(max_workers=16) as pool:
            records = list(pool.map(teacher_episode, jobs))
        results[str(level)] = dict(games=len(records), rows=sum(r['rows'] for r in records))
        print(results[str(level)], flush=True)
    (root / 'result.json').write_text(json.dumps(dict(status='complete', stages=results)), encoding='utf-8')


if __name__ == '__main__':
    run()
