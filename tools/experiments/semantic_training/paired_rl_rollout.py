"""Collect one-reservoir-root paired preference training examples."""

from pathlib import Path
import random

import torch

from gicg_env import ACTION_REROLL
from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.paired_counterfactual import (
    paired_rollouts,
    reservoir_replace,
    sample_alternative_action,
)
from tools.experiments.semantic_training.teams import matchup_key, sample_config
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer
from tools.experiments.semantic_training.decision_budget import DecisionBudget


STATIC_KEYS = (
    'counter_sids',
    'active_slot_mask',
    'char_skill_refs',
    'hook_ir',
    'hook_mask',
    'counter_owners',
    'counter_links',
    'card_links',
    'skill_links',
    'card_hook_links',
)
DECISION_TYPES = ('ordinary', 'reroll', 'all')


def should_collect_root(requested, actual):
    if requested not in DECISION_TYPES:
        raise ValueError(f'unknown decision type: {requested}')
    if actual not in DECISION_TYPES[:2]:
        raise ValueError(f'unknown root decision type: {actual}')
    return requested == 'all' or requested == actual


def aggregate_pair(result, obs, chosen, alternative, decision_type, learner_side):
    differences = [pair['chosen_outcome'] - pair['alternative_outcome'] for pair in result['pairs']]
    if not differences:
        return None
    mean_difference = sum(differences) / result['rollouts']
    if not mean_difference:
        return None
    discordance = sum((difference > 0) != (mean_difference > 0) for difference in differences)
    return dict(
        obs=obs,
        chosen_action=chosen,
        alternative_action=alternative,
        preference=1 if mean_difference > 0 else -1,
        sample_weight=abs(mean_difference),
        mean_difference=mean_difference,
        decision_type=decision_type,
        learner_side=learner_side,
        pair_repeats=result['rollouts'],
        ties=result['ties'],
        discordance=discordance,
        continuation_steps=result['total_steps'],
    )


def episode(args):
    from tools.rule_validation.variants import environment_config

    if len(args) == 8:
        iteration, index, directory, master_seed, variants, pair_repeats, max_steps, opponent_depth = args
        decision_filter = 'ordinary'
    else:
        iteration, index, directory, master_seed, variants, pair_repeats, max_steps, opponent_depth, decision_filter = (
            args
        )
    seed = derive_seed(master_seed, 'paired-rl-game', iteration * 100000 + index)
    cfg = sample_config(ev._CFG, seed)
    with environment_config(cfg, variants, seed, index) as (cfg, manifest):
        return _episode(args, cfg, manifest, seed, pair_repeats, max_steps, opponent_depth, decision_filter)


def _episode(args, cfg, manifest, seed, pair_repeats, max_steps, opponent_depth, decision_filter='ordinary'):
    _, index, directory, _, _, _, _, _ = args[:8]
    agent = ev._AGENT
    learner_side = index % 2
    env = make_env_factory(cfg, None, seed)(0, layout_seed=derive_seed(seed, 'layout'))
    opponent = GreedyPlayer(
        features='F1', depth=ev._OPPONENT_DEPTH, dice_greedy=True, seed=derive_seed(seed, 'opponent')
    )
    continuation_opponent = GreedyPlayer(
        features='F1', depth=opponent_depth, dice_greedy=True, seed=derive_seed(seed, 'paired-opponent')
    )
    reservoir_rng = random.Random(derive_seed(seed, 'paired-reservoir'))
    root, selected, seen = None, None, 0
    ties = 0
    try:
        torch.manual_seed(derive_seed(seed, 'sample'))
        agent.game_start(env.static_obs)
        budget = DecisionBudget(cfg.paradigm['max_game_steps'])
        for _ in budget.iterate(env):
            if env.acting_player == learner_side:
                kinds, _ = env.get_legal_actions()
                decision_type = 'reroll' if len(kinds) and all(kind == ACTION_REROLL for kind in kinds) else 'ordinary'
                obs = agent.observation(env)
                logits = agent.logits(env)
                if len(logits) > 1:
                    temperature = getattr(agent, 'sampling_temperature', 1.0)
                    chosen = int(torch.multinomial((logits / temperature).softmax(-1), 1))
                    alternative = sample_alternative_action(logits, chosen, temperature)
                    if should_collect_root(decision_filter, decision_type):
                        seen, replace = reservoir_replace(seen, reservoir_rng)
                    else:
                        replace = False
                    if replace:
                        if root is not None:
                            root.close()
                        root = env.clone()
                        selected = (
                            dict(obs, **{key: obs[key] for key in STATIC_KEYS}),
                            chosen,
                            alternative,
                            decision_type,
                        )
                else:
                    chosen = 0
                action = chosen
            else:
                action = opponent.select_action(env)
            env.step(action)
        if not env.done:
            raise RuntimeError('paired RL collection did not reach terminal state')
        rows = []
        continuation_steps = 0
        if root is not None:
            obs, chosen, alternative, decision_type = selected
            seeds = [derive_seed(seed, 'paired-continuation', i) for i in range(pair_repeats)]
            result = paired_rollouts(
                root,
                chosen,
                alternative,
                agent,
                continuation_opponent,
                learner_side=learner_side,
                simulation_seeds=seeds,
                max_steps=max_steps,
                decision_type=decision_type,
            )
            ties = result['ties']
            continuation_steps = result['total_steps']
            row = aggregate_pair(result, obs, chosen, alternative, decision_type, learner_side)
            if row is not None:
                rows.append(row)
        path = Path(directory) / f'paired_{index:05d}.pt'
        torch.save(rows, path)
        return {
            'path': str(path),
            'decision_type': decision_filter,
            'selected_decision_type': selected[3] if selected is not None else None,
            'root_seen': seen,
            'root_selected': int(root is not None),
            'pairs': len(rows),
            'ties': ties,
            'side': learner_side,
            'steps': budget.actions,
            'continuation_steps': continuation_steps,
            'matchup': matchup_key(cfg.scenario.team_0, cfg.scenario.team_1),
            'rule_variant': manifest,
        }
    finally:
        if root is not None:
            root.close()
        env.close()
