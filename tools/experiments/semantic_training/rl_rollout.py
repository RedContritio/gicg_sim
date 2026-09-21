"""On-policy semantic trajectories against D1, terminal rewards only."""

from pathlib import Path
import random
import torch

from tools.experiments.semantic_training import evaluate as ev
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.env_factory import make_env_factory
from tools.experiments.semantic_training.teams import sample_config, matchup_key
from training.core.episode_seeds import derive_seed
from training.core.matchup.outcome import terminal_outcome
from tools.experiments.semantic_training.decision_budget import DecisionBudget


def episode(args):
    from tools.rule_validation.variants import environment_config

    iteration, index, _, master_seed = args[:4]
    seed = derive_seed(master_seed, 'rl-game', iteration * 100000 + index)
    cfg = sample_config(ev._CFG, seed)
    with environment_config(cfg, args[4] if len(args) > 4 else None, seed, index) as (cfg, manifest):
        return _episode(args, cfg, manifest)


def _episode(args, cfg, manifest):
    iteration, index, directory, master_seed = args[:4]
    agent = ev._AGENT
    side = index % 2
    seed = derive_seed(master_seed, 'rl-game', iteration * 100000 + index)
    torch.manual_seed(derive_seed(seed, 'sample'))
    rule_stride = args[5] if len(args) > 5 else 0
    rule_rng = random.Random(derive_seed(seed, 'rule-outcomes'))
    game_cfg = sample_config(cfg, seed)
    env = make_env_factory(game_cfg, None, seed)(0, layout_seed=derive_seed(seed, 'layout'))
    opponent = GreedyPlayer(
        features='F1', depth=ev._OPPONENT_DEPTH, dice_greedy=True, seed=derive_seed(seed, 'opponent')
    )
    rows, static = [], None
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
        agent.game_start(env.static_obs)
        budget = DecisionBudget(cfg.paradigm['max_game_steps'])
        for _ in budget.iterate(env):
            if env.acting_player == side:
                obs = agent.observation(env)
                old_value = None
                if hasattr(agent, 'value_head'):
                    from tools.experiments.semantic_training.value_baseline import predict

                    logits, old_value = predict(agent, obs)
                else:
                    logits = agent.logits(env)
                logp = (logits / getattr(agent, 'sampling_temperature', 1.0)).log_softmax(-1)
                action = int(torch.multinomial(logp.exp(), 1))
                if static is None:
                    static = {key: obs[key] for key in keys}
                obs.update(static)
                if len(logits) > 1:
                    rows.append({'obs': obs, 'action': action, 'old_logp': float(logp[action])})
                    if old_value is not None:
                        rows[-1]['old_value'] = old_value
                    if rule_stride and (len(rows) - 1) % rule_stride == 0:
                        from tools.experiments.semantic_training.rule_auxiliary import labels

                        rows[-1]['rule_outcomes'] = labels(env, action, rule_rng)
            else:
                action = opponent.select_action(env)
            env.step(action)
        if not env.done:
            raise RuntimeError('RL collection did not reach terminal state')
        reward = terminal_outcome(env.winner, side)
        for row in rows:
            row.update(reward=reward, reward_encoding='signed_outcome', side=side)
        path = Path(directory) / f'episode_{index:05d}.pt'
        torch.save(rows, path)
        return {
            'side': side,
            'rule_variant': manifest,
            'reward': reward,
            'rows': len(rows),
            'steps': budget.actions,
            'decisions': budget.decisions,
            'internal_decisions': budget.internal,
            'path': str(path),
            'matchup': matchup_key(game_cfg.scenario.team_0, game_cfg.scenario.team_1),
        }
    finally:
        env.close()
