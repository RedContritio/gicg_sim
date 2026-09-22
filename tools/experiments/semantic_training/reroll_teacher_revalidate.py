"""Revalidate leaders from an existing reroll-teacher audit report."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import statistics
import time

from training.core.config.loader import load_cfg
from training.core.episode_seeds import derive_seed
from training.core.env_factory import make_env_factory
from training.core.matchup.greedy_player import GreedyPlayer
from tools.experiments.semantic_training.player_loader import load_semantic_agent
from tools.experiments.semantic_training.reroll_counterfactual import (
    policy_reroll_vector,
    reroll_pool,
)
from tools.experiments.semantic_training.reroll_teacher_support import (
    advance_to_root,
    leader_validation_summary,
    validate_leader,
)


def _run_root(job) -> dict:
    (
        config,
        checkpoint,
        seed,
        record,
        validation_rollouts,
        max_steps,
        allow_unverified,
        align_dice_rng,
    ) = job
    import torch

    torch.set_num_threads(1)
    root_index = int(record['root'])
    cfg = load_cfg(config)
    env = make_env_factory(cfg, None, master_seed=seed)(root_index)
    learner = load_semantic_agent(checkpoint, verify_provenance=not allow_unverified)
    opponent = GreedyPlayer(
        features='F1',
        depth=2,
        dice_greedy=True,
        seed=derive_seed(seed, 'opponent', root_index),
    )
    expected_current = tuple(int(value) for value in record['current'])
    expected_leader = tuple(int(value) for value in record['selection_leader'])
    try:
        prefix_steps = advance_to_root(env, learner, opponent, 0, max_steps)
        current = policy_reroll_vector(env, learner)
        pool = tuple(reroll_pool(env))
        if current != expected_current or prefix_steps != int(record['prefix_steps']):
            raise ValueError(f'root {root_index} current/prefix does not match input report')
        if 'pool' in record and pool != tuple(int(value) for value in record['pool']):
            raise ValueError(f'root {root_index} reroll pool does not match input report')
        seeds = [derive_seed(seed, 'revalidate', root_index, index) for index in range(validation_rollouts)]
        selected, validation, steps, forwards, gains, mean, lower = validate_leader(
            env,
            expected_leader,
            current,
            learner,
            opponent,
            0,
            seeds,
            max_steps,
            align_dice_rng,
        )
        return {
            'root': root_index,
            'current': list(current),
            'selection_leader': list(expected_leader),
            'selection_leader_source': record.get('selection_leader_source'),
            'selection_leader_mean_paired_gain': record.get('selection_leader_mean_paired_gain'),
            'selection_leader_lower_bound': record.get('selection_leader_lower_bound'),
            'prefix_steps': prefix_steps,
            'pool': list(pool),
            'align_dice_rng': align_dice_rng,
            'leader_validation_outcomes': validation,
            'validation_outcomes': validation,
            'validation_steps': steps,
            'validation_forward_calls': forwards,
            'leader_validation_paired_gains': gains,
            'leader_validation_mean_paired_gain': mean,
            'leader_validation_lower_bound': lower,
            'selected': list(selected),
            'selected_source': record.get('selection_leader_source') if selected == expected_leader else 'current',
            'paired_gain': gains if selected == expected_leader else [0.0] * validation_rollouts,
            'mean_paired_gain': mean if selected == expected_leader else 0.0,
        }
    finally:
        env.close()


def _interval(values: list[float]) -> list[float | None]:
    if len(values) < 2:
        return [None, None]
    mean = statistics.mean(values)
    margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return [mean - margin, mean + margin]


def _report_path(value) -> str:
    return str(Path(str(value).replace('\\', '/')))


def run(args: argparse.Namespace) -> dict:
    report = json.loads(args.report.read_text(encoding='utf-8'))
    if not str(report.get('format', '')).startswith('reroll-teacher-audit/1.2.'):
        raise ValueError('input report must use reroll-teacher-audit/1.2.x format')
    records = report.get('records')
    if not isinstance(records, list):
        raise ValueError('input report records must be a list')
    seed = report['seed'] if args.seed is None else args.seed
    align_dice_rng = report.get('align_dice_rng', True) if args.align_dice_rng is None else args.align_dice_rng
    config = _report_path(report['config'])
    checkpoint = _report_path(report['checkpoint'])
    eligible = [record for record in records if tuple(record['selection_leader']) != tuple(record['current'])]
    jobs = [
        (
            config,
            checkpoint,
            seed,
            record,
            args.validation_rollouts,
            args.max_steps,
            args.allow_unverified,
            align_dice_rng,
        )
        for record in eligible
    ]
    started = time.monotonic()
    output_records = []
    with ProcessPoolExecutor(max_workers=min(args.workers, max(1, len(jobs)))) as pool:
        futures = [pool.submit(_run_root, job) for job in jobs]
        for future in as_completed(futures):
            output_records.append(future.result())
    output_records.sort(key=lambda record: record['root'])
    gains = [record['mean_paired_gain'] for record in output_records]
    result = {
        'format': 'reroll-teacher-revalidation/1.0.0',
        'input_report': str(args.report),
        'checkpoint': checkpoint,
        'config': config,
        'seed': seed,
        'seed_domain': 'revalidate',
        'validation_rollouts': args.validation_rollouts,
        'align_dice_rng': align_dice_rng,
        'workers': args.workers,
        'roots_in_input': len(records),
        'roots_revalidated': len(output_records),
        'roots_skipped_current_leader': len(records) - len(output_records),
        'wall_seconds': time.monotonic() - started,
        'mean_root_paired_gain': statistics.mean(gains) if gains else 0.0,
        'normal_95_interval': _interval(gains),
        'records': output_records,
    }
    result.update(leader_validation_summary(output_records))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(args.output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('report', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--validation-rollouts', type=int, default=24)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--max-steps', type=int, default=512)
    parser.add_argument('--allow-unverified', action='store_true')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--align-dice-rng', dest='align_dice_rng', action='store_true')
    group.add_argument('--no-align-dice-rng', dest='align_dice_rng', action='store_false')
    parser.set_defaults(align_dice_rng=None)
    args = parser.parse_args()
    if args.validation_rollouts < 1 or args.workers < 1:
        raise ValueError('validation_rollouts and workers must be positive')
    result = run(args)
    print(json.dumps({key: value for key, value in result.items() if key != 'records'}, indent=2))


if __name__ == '__main__':
    main()
