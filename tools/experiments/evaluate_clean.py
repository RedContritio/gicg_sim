"""Paired-seed evaluation with a real uniform-random policy and draw-aware intervals.

Unlike the legacy periodic evaluator, never overrides a random baseline's
exploration rate. Reports win fraction separately from win+half-draw score.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.skill_abuser import load_skill_catalog
from tools.experiments.eval_ladder import BASELINES, VERSION, make_baseline, evaluation_provenance
from training.core.artifact_io import provenance
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.outcome import terminal_outcome
from training.core.checkpoint import load_net_state_dict
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc._eval_scenarios import generate_eval_scenarios
from training.paradigms.dmc._opponent import RandomPlayer


def interval(scores):
    pairs = np.asarray(scores).reshape(-1, 2).mean(axis=1)
    rng = np.random.default_rng(91000)
    means = pairs[rng.integers(len(pairs), size=(5000, len(pairs)))].mean(axis=1)
    return np.quantile(means, [0.025, 0.975]).tolist()


def evaluate(cfg_path, checkpoint, n, seed=91000):
    if n < 1:
        raise ValueError('evaluation needs at least one scenario')
    cfg = load_cfg(cfg_path)
    s = cfg.scenario
    scenarios = generate_eval_scenarios(seed, n, s.team_0, s.team_1)
    if checkpoint == 'random':
        agent = RandomPlayer(seed)
    else:
        from training.paradigms.dmc.config import DMCParadigmConfig

        shape = DMCParadigmConfig.from_dict(cfg.paradigm).agent
        fresh = str(checkpoint).startswith('fresh:')
        if fresh:
            torch.manual_seed(int(str(checkpoint).split(':', 1)[1]))
        agent = DmcAgent(AgentConfig.from_obs_shape(shape), epsilon=0)
        if not fresh:
            agent.net.load_state_dict(load_net_state_dict(checkpoint))
        agent.net.eval()
    factory = make_env_factory(cfg, None, seed)
    env = None
    layout_seeds = [derive_seed(seed, 'eval-layout', i) for i in range(n)]
    results = {}
    skill_catalog = load_skill_catalog(cfg)
    try:
        for baseline in BASELINES:
            outcomes, truncated = [], 0
            for index, scenario in enumerate(scenarios):
                if env is not None:
                    env.close()
                    env = None
                env = factory(index, layout_seed=layout_seeds[index])
                for side in (0, 1):
                    env.reset(seed=scenario.env_seed, deck_seeds=(scenario.deck_seed_p0, scenario.deck_seed_p1))
                    opponent = make_baseline(baseline, scenario.env_seed + side, skill_catalog)
                    agent.rng.seed(scenario.env_seed + side + 17)
                    for player in (agent, opponent):
                        if hasattr(player, 'game_start'):
                            player.game_start(env.static_obs)
                    for _ in range(cfg.paradigm['max_game_steps']):
                        if env.done:
                            break
                        player = agent if env.acting_player == side else opponent
                        action = player.select_action(env)
                        if not 0 <= action < len(env.get_action_refs()):
                            raise ValueError('evaluation player returned illegal action')
                        env.step(action)
                    if not env.done:
                        raise RuntimeError('evaluation reached step limit before terminal state')
                    winner = env._engine.winner
                    outcomes.append(terminal_outcome(winner, side))
            scores = (np.asarray(outcomes) + 1) / 2
            results[baseline] = {
                'evaluation_version': VERSION,
                'layout_seeds': layout_seeds,
                'games': len(outcomes),
                'wins': outcomes.count(1),
                'draws': outcomes.count(0),
                'losses': outcomes.count(-1),
                'truncated': truncated,
                'win_fraction': outcomes.count(1) / len(outcomes),
                'score': float(scores.mean()),
                'paired_score_ci95': interval(scores),
                'outcomes': outcomes,
            }
    finally:
        if env is not None:
            env.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('checkpoint')
    parser.add_argument('output', type=Path)
    parser.add_argument('--scenarios', type=int, default=16)
    parser.add_argument('--seed', type=int, default=91000)
    args = parser.parse_args()
    torch.set_num_threads(1)
    result = evaluate(args.config, args.checkpoint, args.scenarios, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                'provenance': provenance(),
                'evaluation': evaluation_provenance(),
                'config': str(args.config),
                'checkpoint': args.checkpoint,
                'seed': args.seed,
                'scenarios': args.scenarios,
                'results': result,
            },
            indent=2,
        )
    )
    print(args.output, flush=True)


if __name__ == '__main__':
    main()
