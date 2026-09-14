"""Collect exact one-step or fixed-D1-response terminal labels and paired layouts."""

import numpy as np

from tools.experiments.decision_audit.run import d1
from tools.experiments.evaluate_history import builder
from training.core.env_factory import make_env_factory
from training.core.episode_seeds import derive_seed
from training.core.matchup.greedy_player import _candidate_indices
from training.core.matchup.outcome import terminal_outcome
from training.paradigms.dmc._episode import capture_obs
from training.paradigms.dmc._eval_scenarios import generate_eval_scenarios


def labels(env, side):
    rows = []
    for action in _candidate_indices(env, True):
        snap = env.snapshot()
        try:
            env.step(action)
            mode = 'immediate'
            if not env.done and env.acting_player != side:
                env.step(d1(119999).select_action(env))
                mode = 'fixed_d1_response'
            if env.done:
                rows.append((action, terminal_outcome(env.winner, side), mode))
        finally:
            env.restore(snap)
            env.snapshot_free(snap)
    return rows


def collect(cfg, checkpoint, scenarios, seed):
    agents = [builder(cfg, checkpoint)(seed) for _ in range(2)]
    factory = make_env_factory(cfg, None, seed)
    specs = generate_eval_scenarios(seed, scenarios, cfg.scenario.team_0, cfg.scenario.team_1)
    rows = []
    for index, spec in enumerate(specs):
        for side in (0, 1):
            envs = [factory(index, layout_seed=derive_seed(seed, f'layout-{k}', index)) for k in range(2)]
            opponent = d1(derive_seed(seed, 'opponent', index * 2 + side))
            recorded = 0
            try:
                for env, agent in zip(envs, agents):
                    env.reset(seed=spec.env_seed, deck_seeds=(spec.deck_seed_p0, spec.deck_seed_p1))
                    agent.game_start(env.static_obs)
                a, b = envs
                for step in range(cfg.paradigm['max_game_steps']):
                    assert a.export_view() == b.export_view(), 'paired physical states diverged'
                    assert np.array_equal(a.get_action_identities(), b.get_action_identities())
                    assert np.array_equal(a.get_legal_action_payments(), b.get_legal_action_payments())
                    if a.done:
                        break
                    if a.acting_player == side:
                        hp = [c['hp'] for p in a.export_view()['players'] for c in p['chars'] if c['alive']]
                        if min(hp) <= 6 and recorded < 8:
                            found = labels(a, side)
                            if found:
                                assert found == labels(b, side), 'layout changed terminal labels'
                                obs = [capture_obs(e, n) for e, n in zip(envs, agents)]
                                qs = [
                                    n._forward_logits(
                                        e._get_obs(),
                                        e.get_action_refs(),
                                        e.get_legal_action_payments(),
                                        len(e.get_action_refs()),
                                    )
                                    .cpu()
                                    .numpy()
                                    for e, n in zip(envs, agents)
                                ]
                                rows.append(
                                    {
                                        'game': index * 2 + side,
                                        'scenario': index,
                                        'step': step,
                                        'obs': obs,
                                        'labels': found,
                                        'online_q': qs,
                                    }
                                )
                                recorded += 1
                        action = agents[0].select_action(a)
                    else:
                        action = opponent.select_action(a)
                    for env in envs:
                        env.step(action)
                if not a.done:
                    raise RuntimeError('collection exceeded step budget')
                print(f'collected games={index * 2 + side + 1} states={len(rows)}', flush=True)
            finally:
                for env in envs:
                    env.close()
    return rows
