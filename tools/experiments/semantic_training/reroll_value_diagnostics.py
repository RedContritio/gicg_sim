"""Calibrate a frozen value head on complete macro-reroll successors.

This diagnostic currently uses learner-side 0 roots before the opponent's
round-start reroll; later-side roots require a hidden-dice posterior first.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path
import random
import statistics

import torch

from gicg_env import ACTION_REROLL
from tools.experiments.semantic_training.player_loader import load_semantic_agent
from tools.experiments.semantic_training.reroll_counterfactual import (
    apply_reroll_vector,
    policy_reroll_candidates,
    policy_reroll_vector,
    reroll_pool,
)
from tools.experiments.semantic_training.reroll_teacher_support import advance_to_root, candidate_subset
from tools.experiments.semantic_training.value_baseline import predict, signed_to_expected_score
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.matchup.outcome import terminal_outcome


def _seed_player(player, seed):
    if hasattr(player, 'rng'):
        player.rng.seed(seed)
    elif hasattr(player, 'seed'):
        player.seed(seed)


def _complete_opponent_reroll(env, opponent, seed):
    kinds, _ = env.get_legal_actions()
    if env.done or len(kinds) == 0 or not all(int(kind) == ACTION_REROLL for kind in kinds):
        return
    _seed_player(opponent, seed ^ 0xD2CE)
    vector = policy_reroll_vector(env, opponent)
    apply_reroll_vector(env, vector)


def _successor(root, vector, learner, opponent, seed, learner_side):
    env = root.clone()
    try:
        env.set_simulation_seed(seed)
        apply_reroll_vector(env, vector)
        _complete_opponent_reroll(env, opponent, seed)
        if env.done:
            return None
        if env.acting_player != learner_side:
            raise RuntimeError('macro reroll successor did not return to learner action')
        learner.game_start(env.static_obs)
        obs = learner.observation(env)
        _, value = predict(learner, obs)
        return env, signed_to_expected_score(value)
    except BaseException:
        env.close()
        raise


def _rollout(successor, learner, opponent, learner_side, seed, max_steps):
    env = successor.clone()
    try:
        env.set_simulation_seed(seed)
        learner.game_start(env.static_obs)
        if hasattr(opponent, 'game_start'):
            opponent.game_start(env.static_obs)
        _seed_player(learner, seed ^ 0x51A7)
        _seed_player(opponent, seed ^ 0xD2CE)
        for step in range(max_steps):
            if env.done:
                return signed_to_expected_score(terminal_outcome(env.winner, learner_side)), step
            kinds, _ = env.get_legal_actions()
            if len(kinds) == 0:
                raise RuntimeError('successor has no legal actions')
            player = learner if env.acting_player == learner_side else opponent
            env.step(int(player.select_action(env)))
        raise RuntimeError(f'value calibration exceeded max_steps={max_steps}')
    finally:
        env.close()


def _run_root(job):
    (
        config,
        checkpoint,
        seed,
        root_index,
        candidates_per_root,
        rollouts,
        max_steps,
        allow_unverified,
        candidate_mode,
    ) = job
    torch.set_num_threads(1)
    cfg = load_cfg(config)
    env = make_env_factory(cfg, None, master_seed=seed)(root_index)
    learner = load_semantic_agent(checkpoint, verify_provenance=not allow_unverified)
    opponent = GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=derive_seed(seed, 'opponent', root_index))
    try:
        prefix_steps = advance_to_root(env, learner, opponent, 0, max_steps)
        current = policy_reroll_vector(env, learner)
        model = []
        if candidate_mode == 'sampled':
            model = policy_reroll_candidates(
                env, learner, count=min(3, candidates_per_root), beam_width=max(24, candidates_per_root * 4)
            )
        candidates, sources = candidate_subset(
            env,
            current,
            model,
            candidates_per_root,
            random.Random(derive_seed(seed, 'candidates', root_index)),
            candidate_mode,
        )
        values = []
        target_seeds = [derive_seed(seed, 'target', root_index, index) for index in range(rollouts)]
        state_seed = derive_seed(seed, 'successor', root_index)
        for index, vector in enumerate(candidates):
            successor = _successor(env, vector, learner, opponent, state_seed, 0)
            if successor is None:
                continue
            successor_env, predicted = successor
            try:
                outcomes = [
                    _rollout(successor_env, learner, opponent, 0, target_seed, max_steps)[0]
                    for target_seed in target_seeds
                ]
            finally:
                successor_env.close()
            values.append(
                {
                    'index': index,
                    'vector': list(vector),
                    'source': sources[index],
                    'predicted': predicted,
                    'target_mean': statistics.mean(outcomes),
                    'target_mse': statistics.mean((outcome - predicted) ** 2 for outcome in outcomes),
                    'outcomes': outcomes,
                }
            )
        return {'root': root_index, 'prefix_steps': prefix_steps, 'pool': list(reroll_pool(env)), 'values': values}
    finally:
        env.close()


def _sign(value):
    return 1 if value > 0 else -1 if value < 0 else 0


def _metrics(records):
    rows = [row for record in records for row in record['values']]
    if not rows:
        return {'n': 0, 'pair_direction_accuracy': None, 'root_equal_ranking_concordance': None}
    errors = [row['predicted'] - row['target_mean'] for row in rows]
    root_concordance = []
    current_pairs = []
    for record in records:
        values = record['values']
        pairs = []
        for left in range(len(values)):
            for right in range(left + 1, len(values)):
                pairs.append(
                    (
                        _sign(values[left]['predicted'] - values[right]['predicted']),
                        _sign(values[left]['target_mean'] - values[right]['target_mean']),
                    )
                )
        comparable = [left == right for left, right in pairs if left and right]
        if comparable:
            root_concordance.append(statistics.mean(comparable))
        if values:
            base = values[0]
            for row in values[1:]:
                current_pairs.append(
                    (_sign(row['predicted'] - base['predicted']), _sign(row['target_mean'] - base['target_mean']))
                )
    direction = [left == right for left, right in current_pairs if left and right]
    positive = [left > 0 for left, right in current_pairs if right > 0]
    negative = [left < 0 for left, right in current_pairs if right < 0]
    predicted_positive = [right > 0 for left, right in current_pairs if left > 0]
    bins = ((float('-inf'), 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, float('inf')))
    calibration = []
    for lower, upper in bins:
        part = [row for row in rows if lower <= row['predicted'] < upper]
        part_ids = {id(row) for row in part}
        calibration.append(
            {
                'range': [None if not math.isfinite(lower) else lower, None if not math.isfinite(upper) else upper],
                'n': len(part),
                'roots': sum(any(id(item) in part_ids for item in record['values']) for record in records),
                'predicted_mean': statistics.mean(row['predicted'] for row in part) if part else None,
                'target_mean': statistics.mean(row['target_mean'] for row in part) if part else None,
            }
        )
    target_mean = statistics.mean(row['target_mean'] for row in rows)
    constant_mse = statistics.mean((row['target_mean'] - target_mean) ** 2 for row in rows)
    mse = statistics.mean(error * error for error in errors)
    positive_accuracy = statistics.mean(positive) if positive else None
    negative_accuracy = statistics.mean(negative) if negative else None
    balanced = (
        (positive_accuracy + negative_accuracy) / 2
        if positive_accuracy is not None and negative_accuracy is not None
        else None
    )
    return {
        'n': len(rows),
        'roots': len(records),
        'mse': mse,
        'in_sample_constant_mse': constant_mse,
        'mse_improvement_over_in_sample_constant': constant_mse - mse,
        'mae': statistics.mean(abs(error) for error in errors),
        'bias': statistics.mean(errors),
        'prediction_mean': statistics.mean(row['predicted'] for row in rows),
        'target_mean': statistics.mean(row['target_mean'] for row in rows),
        'calibration_bins': calibration,
        'ranking_roots': len(root_concordance),
        'root_equal_ranking_concordance': statistics.mean(root_concordance) if root_concordance else None,
        'current_pair_comparisons': len(direction),
        'pair_direction_accuracy': statistics.mean(direction) if direction else None,
        'current_positive_comparisons': len(positive),
        'current_negative_comparisons': len(negative),
        'current_positive_accuracy': positive_accuracy,
        'current_negative_accuracy': negative_accuracy,
        'current_direction_balanced_accuracy': balanced,
        'predicted_improvement_count': len(predicted_positive),
        'predicted_improvement_precision': statistics.mean(predicted_positive) if predicted_positive else None,
    }


def run(
    config,
    checkpoint,
    output,
    *,
    seed=936400,
    roots=8,
    root_start=0,
    candidates_per_root=4,
    rollouts=8,
    workers=1,
    max_steps=512,
    allow_unverified_checkpoint=False,
    candidate_mode='sampled',
):
    if min(roots, candidates_per_root, rollouts, workers) < 1:
        raise ValueError('positive calibration budgets required')
    if candidate_mode not in ('sampled', 'exhaustive'):
        raise ValueError('unknown candidate mode')
    jobs = [
        (
            str(config),
            str(checkpoint),
            seed,
            root,
            candidates_per_root,
            rollouts,
            max_steps,
            allow_unverified_checkpoint,
            candidate_mode,
        )
        for root in range(root_start, root_start + roots)
    ]
    if workers == 1:
        records = [_run_root(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=min(workers, roots)) as pool:
            records = list(pool.map(_run_root, jobs))
    records.sort(key=lambda record: record['root'])
    result = {
        'format': 'reroll-value-calibration/1.0.0',
        'scope': 'side-0 pre-opponent-reroll roots; terminal expected score in [0,1]',
        'value_encoding': 'expected_score',
        'value_perspective': 'learner_side',
        'return_definition': 'terminal_expected_score',
        'config': str(config),
        'checkpoint': str(checkpoint),
        'seed': seed,
        'learner_side': 0,
        'roots': roots,
        'root_start': root_start,
        'candidates_per_root': candidates_per_root,
        'rollouts': rollouts,
        'candidate_mode': candidate_mode,
        'records': records,
        'metrics': _metrics(records),
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int, default=936400)
    parser.add_argument('--roots', type=int, default=8)
    parser.add_argument('--root-start', type=int, default=0)
    parser.add_argument('--candidates-per-root', type=int, default=4)
    parser.add_argument('--rollouts', type=int, default=8)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--max-steps', type=int, default=512)
    parser.add_argument('--allow-unverified-checkpoint', action='store_true')
    parser.add_argument('--candidate-mode', choices=('sampled', 'exhaustive'), default='sampled')
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps(result['metrics'], indent=2))


if __name__ == '__main__':
    main()
