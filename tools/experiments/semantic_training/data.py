"""Parallel full-game teacher trajectories, with no hidden-state features in NN input."""

from pathlib import Path
import torch

from tools.experiments.decision_audit.run import d1
from tools.experiments.semantic_training.agent import SemanticAgent
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from tools.experiments.semantic_training.teams import sample_config
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig
from tools.experiments.semantic_training.decision_budget import DecisionBudget


def teacher_episode(args):
    from tools.rule_validation.variants import environment_config

    cfg = load_cfg(args[0])
    seed = derive_seed(args[3] if len(args) > 3 else 123000, 'teacher-game', args[1])
    cfg = sample_config(cfg, seed)
    with environment_config(cfg, args[4] if len(args) > 4 else None, seed, args[1]) as (cfg, manifest):
        return _teacher_episode(args, cfg, manifest)


def _teacher_episode(args, cfg, manifest):
    config, index, directory = args[:3]
    master_seed = args[3] if len(args) > 3 else 123000
    torch.set_num_threads(1)
    torch.manual_seed(master_seed)
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    encoder = SemanticAgent(shape)
    learner = args[5] if len(args) > 5 else None
    if learner:
        from training.core.artifact_io import load_checkpoint

        payload = load_checkpoint(learner, map_location='cpu', weights_only=False)
        encoder.net.load_state_dict(payload['net'])
    seed = derive_seed(master_seed, 'teacher-game', index)
    game_cfg = sample_config(cfg, seed)
    env = make_env_factory(game_cfg, None, seed)(0, layout_seed=derive_seed(master_seed, 'teacher-layout', index))
    players = [GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=seed), d1(seed + 1)]
    if learner:
        players[1] = GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=seed + 1)
    rows = []
    learner_decisions = disagreements = 0
    static = None
    keys = (
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
    try:
        from collections import Counter

        names = env._engine.get_card_names()
        deck_counts = Counter(
            names[r] for p in (0, 1) for r in list(env._engine.hand_refs(p)) + list(env._engine.deck_refs(p))
        )
        encoder.game_start(env.static_obs)
        budget = DecisionBudget(cfg.paradigm['max_game_steps'])
        for _ in budget.iterate(env):
            # D2 demonstrations on both character roles across alternating games.
            teacher = players[0] if env.acting_player == index % 2 else players[1]
            action, info = teacher.select_with_info(env)
            if learner and teacher is players[0]:
                action = encoder.select_action(env)
                learner_decisions += 1
                disagreements += action not in info['tied']
            if teacher is players[0] and len(env.get_legal_actions()[0]) > 1:
                obs = encoder.observation(env)
                if static is None:
                    static = {key: obs[key] for key in keys}
                obs.update(static)
                rows.append({'obs': obs, 'tied': info['tied'], 'executed_action': action})
            env.step(action)
        if not env.done:
            raise RuntimeError('teacher episode exceeded step budget')
        path = Path(directory) / f'episode_{index:05d}.pt'
        torch.save({'rows': rows, 'seed': seed, 'winner': env.winner, 'rule_variant': manifest}, path)
        return {
            'index': index,
            'learner': learner,
            'learner_decisions': learner_decisions,
            'expert_disagreements': disagreements,
            'rule_variant': manifest,
            'rows': len(rows),
            'steps': budget.actions,
            'decisions': budget.decisions,
            'internal_decisions': budget.internal,
            'path': str(path),
            'winner': env.winner,
            'deck_counts': dict(deck_counts),
        }
    finally:
        env.close()
