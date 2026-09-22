"""Counterfactual evaluation primitives for complete reroll selections."""

from __future__ import annotations

from itertools import product
import random
from typing import Iterable

import numpy as np

from gicg_env import ACTION_REROLL, GicgEnv
from training.core.matchup.outcome import terminal_outcome

N_DICE_COLORS = 8
CONFIRM_COLOR = 8
RerollVector = tuple[int, int, int, int, int, int, int, int]


def resample_rollout_hidden_state(
    env: GicgEnv,
    learner_side: int,
    seed: int,
    *,
    sample_opponent_dice: bool,
) -> None:
    if learner_side not in (0, 1):
        raise ValueError('learner_side must be 0 or 1')
    opponent = 1 - learner_side
    engine = env._engine
    learner_deck = list(engine.deck_refs(learner_side))
    opponent_pool = list(engine.hand_refs(opponent)) + list(engine.deck_refs(opponent))
    opponent_hand_size = int(engine.hand_count(opponent))
    rng = random.Random(seed ^ 0x48494444454E)
    rng.shuffle(learner_deck)
    rng.shuffle(opponent_pool)
    env.set_player_deck(learner_side, learner_deck)
    env.set_player_hand(opponent, opponent_pool[:opponent_hand_size])
    env.set_player_deck(opponent, opponent_pool[opponent_hand_size:])
    if sample_opponent_dice:
        total = env.dice_total(opponent)
        np_rng = np.random.default_rng(rng.getrandbits(63))
        dice = np_rng.multinomial(total, np.full(N_DICE_COLORS, 1 / N_DICE_COLORS))
        env.set_player_dice(opponent, dice.tolist())


def _reroll_refs(env: GicgEnv) -> np.ndarray:
    kinds, _ = env.get_legal_actions()
    refs = np.asarray(env.get_action_refs(), dtype=np.int64)
    if len(kinds) == 0 or not np.all(np.asarray(kinds) == ACTION_REROLL):
        raise ValueError('environment is not awaiting a reroll choice')
    if refs.shape != (len(kinds), 3):
        raise ValueError(f'unexpected reroll action refs shape {refs.shape}')
    return refs


def reroll_pool(env: GicgEnv) -> tuple[int, ...]:
    if env.pending_dice_remaining != 1:
        raise ValueError('counterfactual reroll root must have exactly one reroll remaining')
    refs = _reroll_refs(env)
    pool = tuple(int(value) for value in env.dice_counts(env.acting_player))
    if len(pool) != N_DICE_COLORS:
        raise ValueError(f'expected {N_DICE_COLORS} dice colors, got {len(pool)}')
    first_color = next((color for color, count in enumerate(pool) if count), CONFIRM_COLOR)
    if not np.all(refs[:, 2] == first_color):
        raise ValueError('reroll macro action must start before any color choice')
    return pool


def enumerate_reroll_vectors(env: GicgEnv, *, max_candidates: int = 4096) -> list[RerollVector]:
    pool = reroll_pool(env)
    candidate_count = int(np.prod([count + 1 for count in pool], dtype=np.int64))
    if candidate_count > max_candidates:
        raise ValueError(f'reroll candidate count {candidate_count} exceeds limit {max_candidates}')
    return [tuple(int(value) for value in values) for values in product(*(range(count + 1) for count in pool))]


def apply_reroll_vector(env: GicgEnv, vector: Iterable[int]) -> None:
    values = tuple(int(value) for value in vector)
    if len(values) != N_DICE_COLORS:
        raise ValueError(f'reroll vector must have {N_DICE_COLORS} entries')
    pool = reroll_pool(env)
    if any(value < 0 or value > pool[color] for color, value in enumerate(values)):
        raise ValueError('reroll vector exceeds the available dice')

    while True:
        refs = _reroll_refs(env)
        color = int(refs[0, 2])
        if not np.all(refs[:, 2] == color):
            raise ValueError('reroll legal actions contain multiple colors')
        count = 0 if color == CONFIRM_COLOR else values[color]
        matches = np.flatnonzero(refs[:, 1] == count)
        if len(matches) != 1:
            raise ValueError(f'reroll count {count} is unavailable for color {color}')
        env.step(int(matches[0]))
        if color == CONFIRM_COLOR:
            return


def policy_reroll_vector(root: GicgEnv, player) -> RerollVector:
    env = root.clone()
    values = [0] * N_DICE_COLORS
    try:
        reroll_pool(env)
        if hasattr(player, 'game_start'):
            player.game_start(env.static_obs)
        while True:
            refs = _reroll_refs(env)
            action = int(player.select_action(env))
            if action < 0 or action >= len(refs):
                raise ValueError('reroll player returned an illegal action')
            count, color = int(refs[action, 1]), int(refs[action, 2])
            env.step(action)
            if color == CONFIRM_COLOR:
                return tuple(values)
            values[color] = count
    finally:
        env.close()


def policy_reroll_candidates(
    root: GicgEnv,
    player,
    *,
    count: int = 4,
    beam_width: int = 24,
) -> list[RerollVector]:
    if count < 1 or beam_width < count:
        raise ValueError('beam_width must be at least the positive candidate count')
    initial = root.clone()
    beams = [(0.0, (0,) * N_DICE_COLORS, initial)]
    completed: list[tuple[float, RerollVector]] = []
    try:
        reroll_pool(initial)
        if hasattr(player, 'game_start'):
            player.game_start(initial.static_obs)
        while beams:
            expanded = []
            for score, vector, env in beams:
                refs = _reroll_refs(env)
                logits = player.logits(env).detach().cpu().numpy().astype(np.float64)
                if logits.shape != (len(refs),) or not np.isfinite(logits).all():
                    raise ValueError('reroll policy returned invalid logits')
                shifted = logits - logits.max()
                log_probs = shifted - np.log(np.exp(shifted).sum())
                for action, log_prob in enumerate(log_probs):
                    child = env.clone()
                    reroll_count = int(refs[action, 1])
                    color = int(refs[action, 2])
                    values = list(vector)
                    if color != CONFIRM_COLOR:
                        values[color] = reroll_count
                    child.step(action)
                    item = (score + float(log_prob), tuple(values), child)
                    if color == CONFIRM_COLOR:
                        completed.append((item[0], item[1]))
                        child.close()
                    else:
                        expanded.append(item)
                env.close()
            expanded.sort(key=lambda item: (-item[0], item[1]))
            for _, _, env in expanded[beam_width:]:
                env.close()
            beams = expanded[:beam_width]
        completed.sort(key=lambda item: (-item[0], item[1]))
        return [vector for _, vector in completed[:count]]
    finally:
        for _, _, env in beams:
            env.close()


def rollout_candidate(
    root: GicgEnv,
    vector: RerollVector,
    learner,
    opponent,
    *,
    learner_side: int,
    simulation_seed: int,
    max_steps: int = 512,
    align_dice_rng: bool = True,
) -> tuple[float, int, int]:
    if root.acting_player != learner_side:
        raise ValueError('reroll root must belong to the learner side')
    if learner_side != 0:
        raise ValueError('counterfactual rollouts currently support only pre-opponent-reroll side 0 roots')
    env = root.clone()
    try:
        reroll_budget = sum(reroll_pool(root))
        env.set_simulation_seed(simulation_seed)
        resample_rollout_hidden_state(
            env,
            learner_side,
            simulation_seed,
            sample_opponent_dice=learner_side == 0,
        )
        learner.game_start(env.static_obs)
        if hasattr(learner, 'rng'):
            learner.rng.seed(simulation_seed ^ 0x51A7)
        if hasattr(opponent, 'game_start'):
            opponent.game_start(env.static_obs)
        if hasattr(opponent, 'rng'):
            opponent.rng.seed(simulation_seed ^ 0xD2CE)
        elif hasattr(opponent, 'seed'):
            opponent.seed(simulation_seed ^ 0xD2CE)
        apply_reroll_vector(env, vector)
        if align_dice_rng:
            env.advance_simulation_dice_draws(reroll_budget - sum(vector))
        learner_forward_calls = 0
        for step in range(max_steps):
            if env.done:
                return terminal_outcome(env.winner, learner_side), step, learner_forward_calls
            kinds, _ = env.get_legal_actions()
            if len(kinds) == 0:
                raise RuntimeError('non-terminal continuation has no legal actions')
            player = learner if env.acting_player == learner_side else opponent
            if env.acting_player == learner_side:
                learner_forward_calls += 1
            action = int(player.select_action(env))
            if action < 0 or action >= len(kinds):
                raise ValueError('continuation player returned an illegal action')
            env.step(action)
        raise RuntimeError(f'counterfactual continuation exceeded max_steps={max_steps}')
    finally:
        env.close()
