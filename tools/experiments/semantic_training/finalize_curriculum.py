"""Wait for frozen curriculum results, then verify and audit every final policy."""

import argparse
import json
from pathlib import Path
import time

from tools.experiments.semantic_training.card_coverage import run as audit_cards
from tools.experiments.semantic_training.deck_curriculum import card_grades
from tools.experiments.semantic_training.verify_curriculum import run as verify


def checked_coverage(result, candidate, fingerprint):
    if result['status'] != 'complete' or result['checkpoint_sha256'] != candidate['sha256']:
        raise ValueError('incomplete or wrong candidate card audit')
    if result['provenance']['source_observation_sha256'] != fingerprint:
        raise ValueError('card audit environment mismatch')
    rows = result['games']
    if [(r['index'], r['side']) for r in rows] != [(i, s) for i in range(240) for s in (0, 1)]:
        raise ValueError('missing or duplicated card audit games')
    for row in rows:
        if sum(row['starting'].values()) != 30 or any(n not in (1, 2) for n in row['starting'].values()):
            raise ValueError('invalid starting deck size or copy count')
        if not set(row['used']) <= set(row['legal']) <= set(row['seen']):
            raise ValueError('inconsistent card exposure records')
    missing = [name for name in card_grades() if not any(name in r['seen'] for r in rows)]
    if missing:
        raise ValueError(f'original cards never seen in audit: {missing}')
    return {
        'games': len(rows),
        'unplayed_cards': [name for name in card_grades() if not any(r['used'].get(name, 0) for r in rows)],
    }


def run(directory, workers=16, wait_seconds=86400):
    root = Path(directory)
    start = time.monotonic()
    while True:
        status = json.loads((root / 'result.json').read_text(encoding='utf-8'))
        if status['status'] == 'complete':
            break
        if status['status'] == 'failed':
            raise RuntimeError(f'curriculum failed: {status.get("error")}')
        if time.monotonic() - start >= wait_seconds:
            raise TimeoutError('curriculum is still running; no final audits started')
        time.sleep(30)
    verify(root)
    coverage = []
    for candidate in status['final']:
        output = root / f'acceptance_{candidate["seed"]}' / 'card_coverage.json'
        if not output.exists():
            audit_cards('configs/dmc/curriculum_l6.toml', candidate['candidate'], output, 240, workers)
        result = json.loads(output.read_text(encoding='utf-8'))
        summary = checked_coverage(result, candidate, status['provenance']['source_observation_sha256'])
        coverage.append(dict(seed=candidate['seed'], **summary))
    verification = json.loads((root / 'verification.json').read_text(encoding='utf-8'))
    result = dict(
        status='complete',
        strength_gate_passed=verification['strength_gate_passed'],
        coverage=coverage,
        remaining='Pull artifacts and review final report; completion does not imply strength gate passed.',
    )
    (root / 'finalization.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--wait-seconds', type=int, default=86400)
    args = parser.parse_args()
    run(args.directory, args.workers, args.wait_seconds)
