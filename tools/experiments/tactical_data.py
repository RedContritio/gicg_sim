"""Reachable board states and exhaustive one-step engine labels, no HP fixtures."""

import numpy as np

from gicg_env._constants import STEP_CONTINUE, STEP_GAME_OVER, STEP_NEED_TARGET

from training.core.env_factory import make_env_factory
from training.core.matchup.outcome import terminal_outcome
from training.paradigms.dmc._episode import capture_obs


def health(view, side):
    return sum(c['hp'] for c in view['players'][side]['chars'])


def step_checked(env, index):
    """Use the native result code; env.step's info has no illegal_action field.

    This laboratory does not consume shaped rewards or the returned observation.
    Native methods perform the same round advancement as env.step.
    """
    if not 0 <= index < len(env.get_action_refs()):
        raise ValueError('illegal tactical action index')
    engine = env._engine
    result = engine.step_target(index) if engine.has_pending else engine.step(index)
    if result not in (STEP_CONTINUE, STEP_GAME_OVER, STEP_NEED_TARGET):
        raise AssertionError(f'engine rejected tactical action: {result}')


def utility(before, after, side):
    gain = health(after, side) - health(before, side)
    gain -= health(after, 1 - side) - health(before, 1 - side)
    if after['winner'] != -1:
        gain += 20 * terminal_outcome(after['winner'], side)
    return float(gain)


def label_actions(env):
    before = env._engine.export_view()
    side = env.acting_player
    labels = []
    for index in range(len(env.get_action_refs())):
        clone = env.clone()
        try:
            step_checked(clone, index)
            labels.append(utility(before, clone._engine.export_view(), side))
        finally:
            clone.close()
    result = np.asarray(labels, dtype=np.float32)
    if not len(result) or not np.isfinite(result).all():
        raise AssertionError('empty or nonfinite tactical labels')
    return result


def collect(cfg, agent, seeds):
    rows, games = [], []
    for seed in seeds:
        env = make_env_factory(cfg, None, seed)(0)
        rng = np.random.default_rng(seed)
        trace, captured = [], 0
        try:
            env.log_suspend()
            agent.game_start(env.static_obs)
            for step in range(128):
                kinds, _ = env.get_legal_actions()
                if env.done:
                    break
                if step % 8 == 0 and not env._engine.has_pending and captured < 8:
                    obs = capture_obs(env, agent)
                    labels = label_actions(env)
                    if len(labels) != obs['n_legal']:
                        raise AssertionError('label/observation action mismatch')
                    rows.append({'obs': obs, 'utility': labels, 'seed': seed, 'step': step})
                    captured += 1
                kind = rng.choice(np.unique(kinds))
                index = int(rng.choice(np.flatnonzero(kinds == kind)))
                trace.append(index)
                step_checked(env, index)
            games.append({'seed': seed, 'actions': trace, 'captured': captured, 'done': env.done, 'winner': env.winner})
            print('TACTICS COLLECT', seed, captured, flush=True)
        finally:
            env.close()
    if not rows:
        raise ValueError('no tactical states')
    return rows, games
