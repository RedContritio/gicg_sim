"""Collect frozen-policy terminal trajectories for offline value probes."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import time

from tools.experiments.semantic_training.evaluate import initialize
from tools.experiments.semantic_training.rl_rollout import episode


def run(
    config,
    checkpoint,
    output,
    *,
    episodes=64,
    workers=4,
    seed=936500,
    opponent_depth=2,
    allow_unverified_checkpoint=False,
):
    if min(episodes, workers) < 1:
        raise ValueError('positive collection budgets required')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    player_spec = None
    if allow_unverified_checkpoint:
        player_spec = {
            'type': 'semantic_rl',
            'ckpt': str(checkpoint),
            'allow_unverified_checkpoint': True,
        }
    jobs = [(0, index, str(output), seed, None, 0, 'argmax') for index in range(episodes)]
    report = {
        'format': 'semantic-value-rollouts/1.0.0',
        'status': 'running',
        'config': str(config),
        'checkpoint': str(checkpoint),
        'checkpoint_sha256': hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
        'continuation_policy': 'frozen_semantic_argmax',
        'opponent': f'greedy_F1_D{opponent_depth}',
        'reward_encoding': 'signed_outcome',
        'value_perspective': 'acting_player',
        'episodes_requested': episodes,
        'seed': seed,
        'games': [],
    }
    report_path = output / 'report.json'
    started = time.monotonic()

    def save():
        report['wall_seconds'] = time.monotonic() - started
        temporary = output / 'report.tmp'
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(report_path)

    save()
    try:
        with ProcessPoolExecutor(
            max_workers=min(workers, episodes),
            initializer=initialize,
            initargs=(str(config), str(checkpoint), opponent_depth, player_spec),
        ) as pool:
            for row in pool.map(episode, jobs):
                report['games'].append(row)
                save()
        report['status'] = 'complete'
        report['episodes_completed'] = len(report['games'])
        report['environment_steps'] = sum(row['steps'] for row in report['games'])
        report['learner_decisions'] = sum(row['decisions'] for row in report['games'])
        report['stored_rows'] = sum(row['rows'] for row in report['games'])
        save()
        return report
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = f'{type(error).__name__}: {error}'
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--episodes', type=int, default=64)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--seed', type=int, default=936500)
    parser.add_argument('--opponent-depth', type=int, default=2, choices=(1, 2))
    parser.add_argument('--allow-unverified-checkpoint', action='store_true')
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps({key: value for key, value in result.items() if key != 'games'}, indent=2))


if __name__ == '__main__':
    main()
