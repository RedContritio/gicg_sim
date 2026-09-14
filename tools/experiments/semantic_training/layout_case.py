"""Reproduce the first layout-dependent decision in one recorded evaluation case."""

import argparse
import json
from pathlib import Path

import numpy as np

from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.teams import eval_cases, with_teams
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import GreedyPlayer


def run(config, panel_path, index, side, output):
    panel = json.loads(Path(panel_path).read_text(encoding='utf-8'))
    seed = panel['seed']
    ev.initialize(config, panel['checkpoint'], panel['opponent_depth'])
    case = eval_cases(ev._CFG, seed, panel['scenarios'])[index]
    factory = make_env_factory(with_teams(ev._CFG, case.team_0, case.team_1), None, seed)
    envs = [factory(index, layout_seed=derive_seed(seed, 'layout', index * 100 + k)) for k in (0, 1)]
    agents = [ev._AGENT, SemanticAgent(ev._AGENT.cfg)]
    agents[1].net.load_state_dict(agents[0].net.state_dict())
    opponent = GreedyPlayer(
        features='F1',
        depth=panel['opponent_depth'],
        dice_greedy=True,
        seed=derive_seed(seed, 'opponent', index * 2 + side),
    )
    result = dict(index=index, side=side, seed=seed, checkpoint=panel['checkpoint'], difference=None)
    try:
        for env, agent in zip(envs, agents):
            env.reset(seed=case.env_seed, deck_seeds=(case.deck_seed_p0, case.deck_seed_p1))
            agent.game_start(env.static_obs)
        for step in range(ev._CFG.paradigm['max_game_steps']):
            base = envs[0]
            if base.done:
                break
            if base.export_view() != envs[1].export_view():
                raise ValueError('physical states diverged before decision')
            ids, payments = base.get_action_identities(), base.get_legal_action_payments()
            np.testing.assert_array_equal(ids, envs[1].get_action_identities())
            np.testing.assert_array_equal(payments, envs[1].get_legal_action_payments())
            if base.acting_player == side:
                qs = [agent.logits(env) for agent, env in zip(agents, envs)]
                actions = [int((q * 1e5).round().argmax()) for q in qs]
                action = actions[0]
                if actions[0] != actions[1]:
                    labels = base.get_action_labels()
                    selected = sorted(set(actions + [int(q.argmax()) for q in qs]))
                    result['difference'] = dict(
                        step=step,
                        round=base.export_view()['round'],
                        actions=actions,
                        q_max_error=float((qs[0] - qs[1]).abs().max()),
                        alternatives=[
                            dict(
                                index=a,
                                label=labels[a],
                                identity=ids[a].tolist(),
                                payment=payments[a].tolist(),
                                logits=[float(q[a]) for q in qs],
                                rounded=[float((q[a] * 1e5).round()) for q in qs],
                            )
                            for a in selected
                        ],
                    )
                    break
            else:
                action = opponent.select_action(base)
            for env in envs:
                env.step(action)
    finally:
        for env in envs:
            env.close()
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('panel')
    parser.add_argument('index', type=int)
    parser.add_argument('side', type=int, choices=(0, 1))
    parser.add_argument('output')
    args = parser.parse_args()
    run(args.config, args.panel, args.index, args.side, args.output)
