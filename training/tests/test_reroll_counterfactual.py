import math
import random

import pytest

from gicg_env import ACTION_REROLL, GicgEnv
from tools.experiments.semantic_training.reroll_counterfactual import (
    apply_reroll_vector,
    enumerate_reroll_vectors,
    policy_reroll_candidates,
    policy_reroll_vector,
    reroll_pool,
    resample_rollout_hidden_state,
    rollout_candidate,
)
from tools.experiments.semantic_training.reroll_teacher import _qualified_selection
from tools.experiments.semantic_training import reroll_teacher_support as teacher_support


def _reroll_env(seed=41, max_rounds=0):
    env = GicgEnv(['赤蝶'], ['墨客'], seed=seed, data_dir='data', max_rounds=max_rounds)
    env.reset(seed=seed)
    for _ in range(8):
        kinds, _ = env.get_legal_actions()
        if len(kinds) > 0 and all(kind == ACTION_REROLL for kind in kinds):
            break
        env.step(0)
    assert len(kinds) > 0 and all(kind == ACTION_REROLL for kind in kinds)
    return env


class _EndTurnPlayer:
    def game_start(self, static_obs):
        pass

    def select_action(self, env):
        refs = env.get_action_refs()
        if len(refs) and refs[0, 0] == ACTION_REROLL:
            if refs[0, 2] == 8:
                return 0
            return next(i for i, row in enumerate(refs) if row[1] == 0)
        return len(refs) - 1


def test_enumerates_every_complete_reroll_vector():
    env = _reroll_env()
    try:
        pool = reroll_pool(env)
        vectors = enumerate_reroll_vectors(env)
        assert len(vectors) == math.prod(count + 1 for count in pool)
        assert len(set(vectors)) == len(vectors)
        assert (0,) * 8 in vectors
        assert pool in vectors
    finally:
        env.close()


def test_apply_zero_vector_preserves_pool_and_finishes_one_selection():
    env = _reroll_env()
    try:
        owner = env.acting_player
        before = tuple(int(value) for value in env.dice_counts(owner))
        apply_reroll_vector(env, (0,) * 8)
        after = tuple(int(value) for value in env.dice_counts(owner))
        assert after == before
        assert env.acting_player != owner
    finally:
        env.close()


def test_apply_rejects_invalid_vectors_without_mutating_root():
    env = _reroll_env()
    try:
        before = tuple(int(value) for value in env.dice_counts(env.acting_player))
        with pytest.raises(ValueError, match='8 entries'):
            apply_reroll_vector(env, (0,) * 7)
        invalid = list(before)
        invalid[0] += 1
        with pytest.raises(ValueError, match='available dice'):
            apply_reroll_vector(env, invalid)
        assert tuple(int(value) for value in env.dice_counts(env.acting_player)) == before
    finally:
        env.close()


def test_mid_selection_is_not_accepted_as_macro_root():
    env = _reroll_env()
    try:
        env.step(0)
        with pytest.raises(ValueError, match='must start'):
            reroll_pool(env)
    finally:
        env.close()


def test_policy_vector_records_the_complete_selection_without_mutating_root():
    class KeepAllPlayer:
        def select_action(self, env):
            return 0

    env = _reroll_env()
    try:
        before = tuple(int(value) for value in env.dice_counts(env.acting_player))
        assert policy_reroll_vector(env, KeepAllPlayer()) == (0,) * 8
        assert tuple(int(value) for value in env.dice_counts(env.acting_player)) == before
        reroll_pool(env)
    finally:
        env.close()


def test_policy_candidates_include_greedy_and_ranked_alternatives_without_mutating_root():
    class PreferLargerCounts:
        def game_start(self, static_obs):
            pass

        def logits(self, env):
            import torch

            refs = env.get_action_refs()
            return torch.as_tensor(refs[:, 1], dtype=torch.float32)

    env = _reroll_env()
    try:
        before = tuple(int(value) for value in env.dice_counts(env.acting_player))
        candidates = policy_reroll_candidates(env, PreferLargerCounts(), count=3, beam_width=8)
        assert len(candidates) == 3
        assert len(set(candidates)) == 3
        assert candidates[0] == before
        assert all(0 <= value <= before[color] for candidate in candidates for color, value in enumerate(candidate))
        assert tuple(int(value) for value in env.dice_counts(env.acting_player)) == before
        reroll_pool(env)
    finally:
        env.close()


def test_exhaustive_teacher_candidates_keep_current_first_and_cover_all_vectors():
    env = _reroll_env()
    try:
        current = tuple(int(value) for value in env.dice_counts(env.acting_player))
        candidates, sources = teacher_support.candidate_subset(
            env, current, [], count=2, rng=random.Random(7), mode='exhaustive'
        )
        assert candidates[0] == current
        assert sources[0] == 'current'
        assert all(source == 'exhaustive' for source in sources[1:])
        assert len(candidates) == math.prod(value + 1 for value in current)
        assert len(set(candidates)) == len(candidates)
    finally:
        env.close()


def test_teacher_race_reports_raw_leader_separately(monkeypatch):
    current = (0,) * 8
    alternative = (1, 0, 0, 0, 0, 0, 0, 0)

    def fake_evaluate(_env, candidates, _learner, _opponent, _side, seeds, _max_steps, _align):
        outcomes = {','.join(map(str, vector)): [float(vector == alternative)] * len(seeds) for vector in candidates}
        return (
            outcomes,
            {key: [1] * len(values) for key, values in outcomes.items()},
            {key: [0] * len(values) for key, values in outcomes.items()},
        )

    monkeypatch.setattr(teacher_support, 'evaluate_candidates', fake_evaluate)
    result = teacher_support.race_candidates(
        None,
        [current, alternative],
        current,
        None,
        None,
        0,
        [1, 2, 3, 4],
        (2, 4),
        8,
    )
    assert result[6] == alternative
    assert result[7] == 1.0
    assert result[8] == 1.0
    assert result[0] == alternative


def test_teacher_accepts_raw_leader_when_selection_is_uncertain_but_validation_is_clear(monkeypatch):
    current = (0,) * 8
    leader = (1, 0, 0, 0, 0, 0, 0, 0)

    def fake_evaluate(_env, candidates, _learner, _opponent, _side, seeds, _max_steps, _align):
        if seeds == [1, 2]:
            values = {current: [0.0, 0.0], leader: [-1.0, 4.0]}
        else:
            values = {current: [0.0, 0.0], leader: [1.0, 1.0]}
        outcomes = {','.join(map(str, vector)): values[vector] for vector in candidates}
        return (
            outcomes,
            {key: [1] * len(value) for key, value in outcomes.items()},
            {key: [0] * len(value) for key, value in outcomes.items()},
        )

    monkeypatch.setattr(teacher_support, 'evaluate_candidates', fake_evaluate)
    race = teacher_support.race_candidates(None, [current, leader], current, None, None, 0, [1, 2], (2,), 8)
    assert race[6] == leader
    assert race[8] < 0
    selected, _, _, _, gains, mean, lower = teacher_support.validate_leader(
        None, leader, current, None, None, 0, [3, 4], 8
    )
    assert selected == leader
    assert gains == [1.0, 1.0]
    assert mean == 1.0 and lower == 1.0


def test_teacher_rejects_raw_leader_when_independent_validation_is_uncertain(monkeypatch):
    current = (0,) * 8
    leader = (1, 0, 0, 0, 0, 0, 0, 0)

    def fake_evaluate(_env, candidates, _learner, _opponent, _side, _seeds, _max_steps, _align):
        outcomes = {
            ','.join(map(str, vector)): ([0.0, 0.0] if vector == current else [1.0, -1.0]) for vector in candidates
        }
        return outcomes, {key: [1, 1] for key in outcomes}, {key: [0, 0] for key in outcomes}

    monkeypatch.setattr(teacher_support, 'evaluate_candidates', fake_evaluate)
    selected, _, _, _, gains, mean, lower = teacher_support.validate_leader(
        None, leader, current, None, None, 0, [3, 4], 8
    )
    assert selected == current
    assert gains == [1.0, -1.0]
    assert mean == 0.0 and lower < 0


def test_teacher_summary_excludes_current_leaders_and_counts_qualified_roots():
    summary = teacher_support.leader_validation_summary(
        [
            {
                'current': [0] * 8,
                'selection_leader': [0] * 8,
                'selected': [0] * 8,
                'leader_validation_mean_paired_gain': 0.0,
            },
            {
                'current': [0] * 8,
                'selection_leader': [1] + [0] * 7,
                'selected': [1] + [0] * 7,
                'leader_validation_mean_paired_gain': 1.0,
            },
        ]
    )
    assert summary['leader_validation_roots'] == 1
    assert summary['mean_leader_validation_paired_gain'] == 1.0
    assert summary['leader_validation_normal_95_interval'] == [None, None]
    assert summary['qualified_roots'] == 1


def test_rollout_hidden_state_resampling_is_seeded_and_does_not_mutate_root():
    env = _reroll_env()
    first = env.clone()
    second = env.clone()
    try:
        assert env.acting_player == 0
        root_hidden = (
            tuple(env._engine.deck_refs(0)),
            tuple(env._engine.hand_refs(1)),
            tuple(env._engine.deck_refs(1)),
            tuple(env.dice_counts(1)),
        )
        resample_rollout_hidden_state(first, 0, 1234, sample_opponent_dice=True)
        resample_rollout_hidden_state(second, 0, 1234, sample_opponent_dice=True)
        first_hidden = (
            tuple(first._engine.deck_refs(0)),
            tuple(first._engine.hand_refs(1)),
            tuple(first._engine.deck_refs(1)),
            tuple(first.dice_counts(1)),
        )
        second_hidden = (
            tuple(second._engine.deck_refs(0)),
            tuple(second._engine.hand_refs(1)),
            tuple(second._engine.deck_refs(1)),
            tuple(second.dice_counts(1)),
        )
        assert first_hidden == second_hidden
        assert (
            tuple(env._engine.deck_refs(0)),
            tuple(env._engine.hand_refs(1)),
            tuple(env._engine.deck_refs(1)),
            tuple(env.dice_counts(1)),
        ) == root_hidden
    finally:
        second.close()
        first.close()
        env.close()


def test_rollout_candidate_same_vector_and_seed_is_deterministic():
    env = _reroll_env(max_rounds=1)
    try:
        learner = _EndTurnPlayer()
        opponent = _EndTurnPlayer()
        args = dict(
            learner=learner,
            opponent=opponent,
            learner_side=0,
            simulation_seed=1234,
            max_steps=128,
        )
        first = rollout_candidate(env, (0,) * 8, **args)
        second = rollout_candidate(env, (0,) * 8, **args)
        assert first == second
    finally:
        env.close()


def test_rollout_candidate_rng_alignment_is_optional_and_legal():
    env = _reroll_env(max_rounds=1)
    try:
        learner = _EndTurnPlayer()
        opponent = _EndTurnPlayer()
        vector = tuple(1 if count else 0 for count in env.dice_counts(0))
        common = dict(
            root=env,
            vector=vector,
            learner=learner,
            opponent=opponent,
            learner_side=0,
            simulation_seed=4321,
            max_steps=128,
        )
        aligned = rollout_candidate(align_dice_rng=True, **common)
        unaligned = rollout_candidate(align_dice_rng=False, **common)
        assert aligned[1] > 0 and unaligned[1] > 0
        assert aligned[0] in (-1.0, 0.0, 1.0)
        assert unaligned[0] in (-1.0, 0.0, 1.0)
    finally:
        env.close()


def test_teacher_switches_only_when_paired_selection_lower_bound_is_positive():
    current = (0,) * 8
    alternative = (1, 0, 0, 0, 0, 0, 0, 0)
    outcomes = {
        ','.join(map(str, current)): [-1.0] * 32,
        ','.join(map(str, alternative)): [1.0] * 32,
    }
    selected, lower = _qualified_selection([current, alternative], current, outcomes)
    assert selected == alternative
    assert lower == 2.0


def test_teacher_retains_current_when_selection_gain_is_not_confident():
    current = (0,) * 8
    alternative = (1, 0, 0, 0, 0, 0, 0, 0)
    outcomes = {
        ','.join(map(str, current)): [-1.0, 1.0] * 16,
        ','.join(map(str, alternative)): [1.0, -1.0] * 16,
    }
    selected, lower = _qualified_selection([current, alternative], current, outcomes)
    assert selected == current
    assert lower <= 0
