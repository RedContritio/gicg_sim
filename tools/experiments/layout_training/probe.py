"""Isolate each shuffle axis on identical physical trajectories; parallel CPU jobs."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.decision_audit.run import d1
from tools.experiments.evaluate_history import builder
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.paradigms.dmc._eval_scenarios import generate_eval_scenarios

AXES = ('shuffle_counters', 'shuffle_hooks', 'shuffle_cards', 'shuffle_skill_slots')


def game(args):
    config, checkpoint, index, side = args
    torch.set_num_threads(1)
    cfg = load_cfg(config)
    spec = generate_eval_scenarios(121000, index + 1, cfg.scenario.team_0, cfg.scenario.team_1)[index]
    settings = [('base', 0)] + [(axis, layout) for axis in AXES for layout in (0, 1)]
    envs, agents = [], []
    results = {axis: [] for axis in AXES}
    try:
        for axis, layout in settings:
            obs = {name: name == axis for name in AXES} | {'include_char_skill_refs': True}
            factory = make_env_factory(cfg, obs, 121000)
            env = factory(index, layout_seed=derive_seed(121000, f'axis-layout-{layout}', index))
            envs.append(env)
            env.reset(seed=spec.env_seed, deck_seeds=(spec.deck_seed_p0, spec.deck_seed_p1))
            agent = builder(cfg, checkpoint)(0)
            agent.game_start(env.static_obs)
            agents.append(agent)
        base = envs[0]
        opponent = d1(derive_seed(121000, 'opponent', index * 2 + side))
        for step in range(cfg.paradigm['max_game_steps']):
            for env in envs[1:]:
                assert base.export_view() == env.export_view()
                assert np.array_equal(base.get_action_identities(), env.get_action_identities())
                assert np.array_equal(base.get_legal_action_payments(), env.get_legal_action_payments())
            if base.done:
                break
            if base.acting_player == side:
                qs = [
                    agent._forward_logits(
                        env._get_obs(),
                        env.get_action_refs(),
                        env.get_legal_action_payments(),
                        len(env.get_action_refs()),
                    )
                    .cpu()
                    .numpy()
                    for env, agent in zip(envs, agents)
                ]
                for k, axis in enumerate(AXES):
                    a, b = qs[1 + k * 2 : 3 + k * 2]
                    i, j = int(a.argmax()), int(b.argmax())
                    refs = base.get_action_refs()
                    results[axis].append(
                        {
                            'step': step,
                            'q_mae': float(np.mean(np.abs(a - b))),
                            'q_max': float(np.max(np.abs(a - b))),
                            'action_changed': i != j,
                            'logical_changed': not np.array_equal(refs[i], refs[j]),
                        }
                    )
                action = int(qs[0].argmax())
            else:
                action = opponent.select_action(base)
            for env in envs:
                env.step(action)
        if not base.done:
            raise RuntimeError('probe did not terminate')
        return {'index': index, 'side': side, 'axes': results}
    finally:
        for env in envs:
            env.close()


def run(config, checkpoint, output, workers=4):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    jobs = [(config, checkpoint, i, side) for i in range(4) for side in (0, 1)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        games = list(pool.map(game, jobs))
    summary = {}
    for axis in AXES:
        rows = [r for g in games for r in g['axes'][axis]]
        summary[axis] = {
            'states': len(rows),
            'mean_q_mae': float(np.mean([r['q_mae'] for r in rows])),
            'max_q_difference': max(r['q_max'] for r in rows),
            'action_changed': sum(r['action_changed'] for r in rows),
            'logical_changed': sum(r['logical_changed'] for r in rows),
        }
    result = {
        'status': 'complete',
        'checkpoint': checkpoint,
        'seed': 121000,
        'trajectory': 'original NN in all-shuffle-disabled observation vs D1',
        'games': games,
        'summary': summary,
    }
    (root / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('output')
    p.add_argument('--workers', type=int, default=4)
    a = p.parse_args()
    run(a.config, a.checkpoint, a.output, a.workers)
