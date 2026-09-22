"""Validate complete-reroll counterfactual choices with terminal continuations."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import random
import statistics
import time

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer
from tools.experiments.semantic_training.player_loader import load_semantic_agent
from tools.experiments.semantic_training.reroll_counterfactual import (
    policy_reroll_candidates,
    policy_reroll_vector,
    reroll_pool,
)
from tools.experiments.semantic_training.reroll_teacher_support import (
    advance_to_root as _advance_to_root,
    candidate_subset as _candidate_subset,
    qualified_selection,
    race_candidates as _race_candidates,
    leader_validation_summary as _leader_validation_summary,
    validate_leader as _validate_leader,
)

_qualified_selection = qualified_selection


def _run_root(job) -> dict:
    (
        config,
        checkpoint,
        seed,
        root_index,
        candidates_per_root,
        selection_schedule,
        validation_rollouts,
        max_steps,
        allow_unverified,
        candidate_mode,
        align_dice_rng,
    ) = job
    import torch

    torch.set_num_threads(1)
    cfg = load_cfg(config)
    env_factory = make_env_factory(cfg, None, master_seed=seed)
    learner = load_semantic_agent(
        str(checkpoint),
        verify_provenance=not allow_unverified,
    )
    opponent = GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=derive_seed(seed, 'opponent', root_index))
    rng = random.Random(derive_seed(seed, 'candidates', root_index))
    learner_side = 0
    env = env_factory(root_index)
    started = time.monotonic()
    try:
        prefix_steps = _advance_to_root(env, learner, opponent, learner_side, max_steps)
        current = policy_reroll_vector(env, learner)
        model_candidates = []
        if candidate_mode == 'sampled':
            model_candidates = policy_reroll_candidates(
                env,
                learner,
                count=min(3, candidates_per_root),
                beam_width=max(24, candidates_per_root * 4),
            )
        candidates, candidate_sources = _candidate_subset(
            env, current, model_candidates, candidates_per_root, rng, candidate_mode
        )
        select_seeds = [derive_seed(seed, 'select', root_index, i) for i in range(selection_schedule[-1])]
        validation_seeds = [derive_seed(seed, 'validate', root_index, i) for i in range(validation_rollouts)]
        (
            leader,
            selection_lower_bound,
            selection,
            selection_steps,
            selection_forward_calls,
            selection_rounds,
            race_leader,
            leader_mean,
            leader_lower,
        ) = _race_candidates(
            env,
            candidates,
            current,
            learner,
            opponent,
            learner_side,
            select_seeds,
            selection_schedule,
            max_steps,
            align_dice_rng,
        )
        if leader != race_leader:
            raise RuntimeError('reroll race returned inconsistent selection leader')
        (
            selected,
            validation,
            validation_steps,
            validation_forward_calls,
            leader_validation_gains,
            leader_validation_mean,
            leader_validation_lower,
        ) = _validate_leader(
            env,
            leader,
            current,
            learner,
            opponent,
            learner_side,
            validation_seeds,
            max_steps,
            align_dice_rng,
        )
        paired = leader_validation_gains if selected == leader else [0.0] * validation_rollouts
        selected_index = candidates.index(selected)
        return {
            'root': root_index,
            'learner_side': learner_side,
            'prefix_steps': prefix_steps,
            'pool': list(reroll_pool(env)),
            'current': list(current),
            'selected': list(selected),
            'candidates': [list(vector) for vector in candidates],
            'candidate_sources': candidate_sources,
            'selected_source': candidate_sources[selected_index],
            'candidate_mode': candidate_mode,
            'align_dice_rng': align_dice_rng,
            'selection_outcomes': selection,
            'selection_steps': selection_steps,
            'selection_forward_calls': selection_forward_calls,
            'selection_rounds': selection_rounds,
            'selection_leader': list(leader),
            'selection_leader_source': candidate_sources[candidates.index(leader)],
            'selection_leader_mean_paired_gain': leader_mean,
            'selection_leader_lower_bound': leader_lower,
            'selection_lower_bound': selection_lower_bound,
            'leader_validation_outcomes': validation,
            'leader_validation_paired_gains': leader_validation_gains,
            'leader_validation_mean_paired_gain': leader_validation_mean,
            'leader_validation_lower_bound': leader_validation_lower,
            'validation_outcomes': validation,
            'validation_steps': validation_steps,
            'validation_forward_calls': validation_forward_calls,
            'selection_env_steps': sum(map(sum, selection_steps.values())),
            'validation_env_steps': sum(map(sum, validation_steps.values())),
            'selection_network_forwards': sum(map(sum, selection_forward_calls.values())),
            'validation_network_forwards': sum(map(sum, validation_forward_calls.values())),
            'paired_gain': paired,
            'mean_paired_gain': statistics.mean(paired),
            'wall_seconds': time.monotonic() - started,
        }
    finally:
        env.close()


def run(args: argparse.Namespace) -> dict:
    if args.roots < 1 or args.workers < 1:
        raise ValueError('roots and workers must be positive')
    if args.root_start < 0:
        raise ValueError('root_start must be non-negative')
    schedule = tuple(int(value) for value in args.selection_schedule.split(','))
    if not schedule or schedule[0] < 1 or any(left >= right for left, right in zip(schedule, schedule[1:])):
        raise ValueError('selection_schedule must contain increasing positive integers')
    if args.validation_rollouts < 1:
        raise ValueError('validation_rollouts must be positive')
    if args.candidate_mode not in ('sampled', 'exhaustive'):
        raise ValueError("candidate_mode must be 'sampled' or 'exhaustive'")
    if args.candidate_mode == 'sampled' and args.candidates_per_root < 2:
        raise ValueError('candidates_per_root must be at least 2 in sampled mode')
    started = time.monotonic()
    jobs = [
        (
            str(args.config),
            str(args.checkpoint),
            args.seed,
            root_index,
            args.candidates_per_root,
            schedule,
            args.validation_rollouts,
            args.max_steps,
            args.allow_unverified,
            args.candidate_mode,
            args.align_dice_rng,
        )
        for root_index in range(args.root_start, args.root_start + args.roots)
    ]
    records = []
    with ProcessPoolExecutor(max_workers=min(args.workers, args.roots)) as pool:
        futures = {pool.submit(_run_root, job): job[3] for job in jobs}
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            print(
                json.dumps(
                    {
                        'root': record['root'],
                        'mean_paired_gain': record['mean_paired_gain'],
                        'wall_seconds': record['wall_seconds'],
                    }
                ),
                flush=True,
            )
    records.sort(key=lambda record: record['root'])

    root_gains = [record['mean_paired_gain'] for record in records]
    mean_gain = statistics.mean(root_gains)
    if len(root_gains) > 1:
        se = statistics.stdev(root_gains) / math.sqrt(len(root_gains))
        interval = [mean_gain - 1.96 * se, mean_gain + 1.96 * se]
    else:
        interval = [None, None]
    result = {
        'format': 'reroll-teacher-audit/1.2.0',
        'checkpoint': str(args.checkpoint),
        'config': str(args.config),
        'seed': args.seed,
        'root_start': args.root_start,
        'roots': args.roots,
        'candidates_per_root': args.candidates_per_root,
        'candidate_mode': args.candidate_mode,
        'selection_schedule': list(schedule),
        'validation_rollouts': args.validation_rollouts,
        'align_dice_rng': args.align_dice_rng,
        'workers': args.workers,
        'learner_side': 0,
        'wall_seconds': time.monotonic() - started,
        'mean_root_paired_gain': mean_gain,
        'normal_95_interval': interval,
        'records': records,
    }
    result.update(_leader_validation_summary(records))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(args.output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('config', type=Path)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int, default=920_001)
    parser.add_argument('--roots', type=int, default=16)
    parser.add_argument('--root-start', type=int, default=0)
    parser.add_argument('--candidates-per-root', type=int, default=6)
    parser.add_argument('--selection-schedule', default='4,8,16,32')
    parser.add_argument('--validation-rollouts', type=int, default=24)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--max-steps', type=int, default=512)
    parser.add_argument('--allow-unverified', action='store_true')
    parser.add_argument('--candidate-mode', choices=('sampled', 'exhaustive'), default='sampled')
    parser.add_argument('--no-align-dice-rng', dest='align_dice_rng', action='store_false')
    parser.set_defaults(align_dice_rng=True)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({key: value for key, value in result.items() if key != 'records'}, indent=2))


if __name__ == '__main__':
    main()
