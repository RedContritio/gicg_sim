"""Candidate discovery and paired evaluation for the reroll teacher."""

from __future__ import annotations

import math
import random
import statistics

import numpy as np

from gicg_env import ACTION_REROLL
from tools.experiments.semantic_training.reroll_counterfactual import (
    RerollVector,
    enumerate_reroll_vectors,
    reroll_pool,
    rollout_candidate,
)


def advance_to_root(env, learner, opponent, learner_side: int, max_steps: int) -> int:
    learner.game_start(env.static_obs)
    if hasattr(opponent, 'game_start'):
        opponent.game_start(env.static_obs)
    for step in range(max_steps):
        if env.done:
            raise RuntimeError('game ended before the learner reroll root')
        kinds, _ = env.get_legal_actions()
        if env.acting_player == learner_side and len(kinds) > 0 and bool(np.all(np.asarray(kinds) == ACTION_REROLL)):
            reroll_pool(env)
            return step
        player = learner if env.acting_player == learner_side else opponent
        env.step(int(player.select_action(env)))
    raise RuntimeError(f'learner reroll root not reached within {max_steps} steps')


def candidate_subset(
    env,
    current: RerollVector,
    model_candidates: list[RerollVector],
    count: int,
    rng: random.Random,
    mode: str = 'sampled',
) -> tuple[list[RerollVector], list[str]]:
    if mode not in ('sampled', 'exhaustive'):
        raise ValueError("candidate mode must be 'sampled' or 'exhaustive'")
    if mode == 'sampled' and count < 2:
        raise ValueError('candidates_per_root must be at least 2 in sampled mode')
    pool = reroll_pool(env)
    all_vectors = enumerate_reroll_vectors(env)
    if mode == 'exhaustive':
        candidates = [current, *[vector for vector in all_vectors if vector != current]]
        return candidates, ['current', *(['exhaustive'] * (len(candidates) - 1))]
    chosen = [current]
    sources = ['current']
    for candidate in model_candidates:
        if candidate not in chosen and len(chosen) < count:
            chosen.append(candidate)
            sources.append('model')
    for source, boundary in (('keep_all', (0,) * 8), ('reroll_all', tuple(pool))):
        if boundary not in chosen and len(chosen) < count:
            chosen.append(boundary)
            sources.append(source)
    remaining = [vector for vector in all_vectors if vector not in chosen]
    rng.shuffle(remaining)
    random_candidates = remaining[: max(0, count - len(chosen))]
    chosen.extend(random_candidates)
    sources.extend(['random'] * len(random_candidates))
    return chosen, sources


def evaluate_candidates(
    env,
    candidates,
    learner,
    opponent,
    learner_side,
    seeds,
    max_steps,
    align_dice_rng: bool = True,
):
    outcomes, steps, forward_calls = {}, {}, {}
    for vector in candidates:
        key = vector_key(vector)
        samples = [
            rollout_candidate(
                env,
                vector,
                learner,
                opponent,
                learner_side=learner_side,
                simulation_seed=seed,
                max_steps=max_steps,
                align_dice_rng=align_dice_rng,
            )
            for seed in seeds
        ]
        outcomes[key] = [value for value, _, _ in samples]
        steps[key] = [value for _, value, _ in samples]
        forward_calls[key] = [value for _, _, value in samples]
    return outcomes, steps, forward_calls


def vector_key(vector: RerollVector) -> str:
    return ','.join(str(value) for value in vector)


def _merge_samples(target: dict[str, list], source: dict[str, list]) -> None:
    for key, values in source.items():
        target.setdefault(key, []).extend(values)


def paired_stats(
    leader: RerollVector,
    current: RerollVector,
    outcomes: dict[str, list[float]],
) -> tuple[float, float]:
    if leader == current:
        return 0.0, 0.0
    paired = [
        alternative - baseline
        for alternative, baseline in zip(outcomes[vector_key(leader)], outcomes[vector_key(current)])
    ]
    if not paired:
        return float('-inf'), float('-inf')
    mean = statistics.mean(paired)
    if len(paired) < 2:
        return mean, float('-inf')
    lower = mean - 1.96 * statistics.stdev(paired) / math.sqrt(len(paired))
    return mean, lower


def qualified_selection(
    candidates: list[RerollVector],
    current: RerollVector,
    outcomes: dict[str, list[float]],
) -> tuple[RerollVector, float]:
    leader = max(candidates, key=lambda vector: statistics.mean(outcomes[vector_key(vector)]))
    _, lower = paired_stats(leader, current, outcomes)
    return (leader, lower) if leader != current and lower > 0 else (current, lower)


def validate_leader(
    env,
    leader: RerollVector,
    current: RerollVector,
    learner,
    opponent,
    learner_side,
    seeds,
    max_steps,
    align_dice_rng: bool = True,
):
    if leader == current:
        empty = {vector_key(current): []}
        return current, empty, empty.copy(), empty.copy(), [0.0] * len(seeds), 0.0, 0.0
    validation, steps, forward_calls = evaluate_candidates(
        env,
        [current, leader],
        learner,
        opponent,
        learner_side,
        seeds,
        max_steps,
        align_dice_rng,
    )
    current_values = validation[vector_key(current)]
    leader_values = validation[vector_key(leader)]
    gains = [leader_value - current_value for leader_value, current_value in zip(leader_values, current_values)]
    mean, lower = paired_stats(leader, current, validation)
    selected = leader if lower > 0 else current
    return selected, validation, steps, forward_calls, gains, mean, lower


def leader_validation_summary(records: list[dict]) -> dict:
    validated = [record for record in records if tuple(record['selection_leader']) != tuple(record['current'])]
    means = [float(record['leader_validation_mean_paired_gain']) for record in validated]
    if len(means) < 2:
        interval = [None, None]
    else:
        mean = statistics.mean(means)
        interval = [
            mean - 1.96 * statistics.stdev(means) / math.sqrt(len(means)),
            mean + 1.96 * statistics.stdev(means) / math.sqrt(len(means)),
        ]
    return {
        'leader_validation_roots': len(validated),
        'mean_leader_validation_paired_gain': statistics.mean(means) if means else 0.0,
        'leader_validation_normal_95_interval': interval,
        'qualified_roots': sum(tuple(record['selected']) != tuple(record['current']) for record in records),
    }


def race_candidates(
    env,
    candidates,
    current,
    learner,
    opponent,
    learner_side,
    seeds,
    schedule,
    max_steps,
    align_dice_rng: bool = True,
):
    outcomes: dict[str, list[float]] = {}
    steps: dict[str, list[int]] = {}
    forward_calls: dict[str, list[int]] = {}
    active = list(candidates)
    rounds = []
    previous = 0
    candidate_order = {vector: index for index, vector in enumerate(candidates)}
    for stage, target in enumerate(schedule):
        block = seeds[previous:target]
        partial_outcomes, partial_steps, partial_forwards = evaluate_candidates(
            env,
            active,
            learner,
            opponent,
            learner_side,
            block,
            max_steps,
            align_dice_rng,
        )
        _merge_samples(outcomes, partial_outcomes)
        _merge_samples(steps, partial_steps)
        _merge_samples(forward_calls, partial_forwards)
        means = {vector: statistics.mean(outcomes[vector_key(vector)]) for vector in active}
        before = list(active)
        if stage + 1 < len(schedule):
            alternatives = sorted(
                (vector for vector in active if vector != current),
                key=lambda vector: (-means[vector], candidate_order[vector]),
            )
            active = [current, *alternatives[: max(1, math.ceil(len(alternatives) / 2))]]
        rounds.append(
            {
                'rollouts': target,
                'active_before': [list(vector) for vector in before],
                'active_after': [list(vector) for vector in active],
            }
        )
        previous = target
    leader = max(active, key=lambda vector: statistics.mean(outcomes[vector_key(vector)]))
    leader_mean, leader_lower = paired_stats(leader, current, outcomes)
    selected = leader
    qualified_lower = leader_lower
    return (
        selected,
        qualified_lower,
        outcomes,
        steps,
        forward_calls,
        rounds,
        leader,
        leader_mean,
        leader_lower,
    )
