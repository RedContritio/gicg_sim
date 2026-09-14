"""Same physical states, four layouts: logical/payment agreement and Q error."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np

from tools.experiments.decision_audit.run import d1
from tools.experiments.semantic_training import evaluate as ev
from tools.experiments.semantic_training.agent import SemanticAgent
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from tools.experiments.semantic_training.teams import eval_cases, with_teams


def check(job):
    index, side, scenario, seed = job
    factory = make_env_factory(with_teams(ev._CFG, scenario.team_0, scenario.team_1), None, seed)
    agents = [ev._AGENT] + [SemanticAgent(ev._AGENT.cfg) for _ in range(3)]
    for agent in agents[1:]:
        agent.net.load_state_dict(ev._AGENT.net.state_dict())
    envs = [factory(index, layout_seed=derive_seed(seed, 'layout', index * 100 + k)) for k in range(4)]
    opponent = d1(derive_seed(seed, 'opponent', index * 2 + side))
    result = dict(states=0, comparisons=0, logical_equal=0, payment_equal=0, q_max_error=0.0, q_abs_sum=0.0, q_count=0)
    try:
        for env, agent in zip(envs, agents):
            env.reset(seed=scenario.env_seed, deck_seeds=(scenario.deck_seed_p0, scenario.deck_seed_p1))
            agent.game_start(env.static_obs)
        for _ in range(ev._CFG.paradigm['max_game_steps']):
            base = envs[0]
            if base.done:
                break
            ids = base.get_action_identities()
            pay = base.get_legal_action_payments()
            for env in envs[1:]:
                if base.export_view() != env.export_view():
                    raise ValueError('physical states diverged')
                np.testing.assert_array_equal(ids, env.get_action_identities())
                np.testing.assert_array_equal(pay, env.get_legal_action_payments())
            if base.acting_player == side:
                qs = [agent.logits(env).cpu().numpy() for agent, env in zip(agents, envs)]
                actions = [int(np.round(q * 1e5).argmax()) for q in qs]
                action = actions[0]
                result['states'] += 1
                for q, chosen in zip(qs[1:], actions[1:]):
                    logical = bool(np.array_equal(ids[action], ids[chosen]))
                    result['comparisons'] += 1
                    result['logical_equal'] += logical
                    result['payment_equal'] += logical and bool(np.array_equal(pay[action], pay[chosen]))
                    diff = np.abs(q - qs[0])
                    result['q_max_error'] = max(result['q_max_error'], float(diff.max()))
                    result['q_abs_sum'] += float(diff.sum())
                    result['q_count'] += len(diff)
            else:
                action = opponent.select_action(base)
            for env in envs:
                env.step(action)
        if not all(env.done for env in envs):
            raise RuntimeError('stability game exceeded budget')
        return result
    finally:
        for env in envs:
            env.close()


def run(config, checkpoint, output, scenarios=64, workers=16, seed=126000):
    cfg = load_cfg(config)
    cases = eval_cases(cfg, seed, scenarios)
    jobs = [(i, side, case, seed) for i, case in enumerate(cases) for side in (0, 1)]
    with ProcessPoolExecutor(max_workers=workers, initializer=ev.initialize, initargs=(config, checkpoint)) as pool:
        rows = list(pool.map(check, jobs))
    result = {key: sum(r[key] for r in rows) for key in rows[0]}
    result['q_max_error'] = max(r['q_max_error'] for r in rows)
    result['q_mae'] = result['q_abs_sum'] / result['q_count']
    result['logical_agreement'] = result['logical_equal'] / result['comparisons']
    result['payment_agreement'] = result['payment_equal'] / result['comparisons']
    result.update(seed=seed, scenarios=scenarios, layouts=4, status='complete', checkpoint=checkpoint)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    print(result, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('output')
    p.add_argument('--scenarios', type=int, default=64)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--seed', type=int, default=126000)
    a = p.parse_args()
    run(a.config, a.checkpoint, a.output, a.scenarios, a.workers, a.seed)
