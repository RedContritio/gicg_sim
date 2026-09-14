"""Read-only decision checks and clone/snapshot transition differential checks."""

import numpy as np
import torch
from tools.experiments.action_audit import check_action_aliases


def decision(env, max_actions):
    # Action query can intentionally enter a new round; stabilize that boundary
    # before requiring subsequent queries to be read-only.
    kinds, _ = env.get_legal_actions()
    refs, payments = env.get_action_refs(), env.get_legal_action_payments()
    if not env.done and not 0 < len(kinds) <= max_actions:
        raise AssertionError(f'legal action capacity/empty set: {len(kinds)} / {max_actions}')
    if len(refs) != len(kinds) or len(payments) != len(kinds):
        raise AssertionError('action/ref/payment alignment failed')
    check_action_aliases(env)
    if not np.isfinite(env._get_obs()).all() or not np.isfinite(payments).all() or (payments < 0).any():
        raise AssertionError('nonfinite observation or invalid payment')
    return kinds, refs.copy(), payments.copy()


def query_readonly(env, expected):
    view = env.export_view()
    raw = [env._engine.get_dynamic_obs(p) for p in (0, 1)]
    for _ in range(2):
        actual = decision(env, len(expected[0]))
        for want, got in zip(expected, actual):
            np.testing.assert_array_equal(want, got)
    if view != env.export_view():
        raise AssertionError('observation/action query mutated public game state')
    for p in (0, 1):
        np.testing.assert_array_equal(raw[p], env._engine.get_dynamic_obs(p))


def compare(left, right, max_actions):
    a, b = decision(left, max_actions), decision(right, max_actions)
    for want, got in zip(a, b):
        np.testing.assert_array_equal(want, got)
    if left.export_view() != right.export_view():
        raise AssertionError('clone/snapshot transition state diverged')
    for p in (0, 1):
        np.testing.assert_array_equal(left._engine.get_dynamic_obs(p), right._engine.get_dynamic_obs(p))
    np.testing.assert_array_equal(left._get_obs(), right._get_obs())


def check_privacy(env):
    p, enemy = env.acting_player, 1 - env.acting_player
    branch = env.clone()
    try:
        before = branch._get_obs()
        branch.set_player_dice(enemy, [0, 0, 0, 0, 0, 0, 0, 17])
        branch.set_simulation_seed(987654321)
        np.testing.assert_array_equal(before, branch._get_obs())
    finally:
        branch.close()


def transition(env, index, max_actions):
    # The untouched clone catches query-induced RNG changes too: it does NOT
    # execute the extra read-only probes before taking the chosen action.
    branch = env.clone()
    snap = env.snapshot()
    try:
        expected = decision(branch, max_actions)
        query_readonly(env, expected)
        env.step(index)
        branch.step(index)
        compare(env, branch, max_actions)
        env.restore(snap)
        env.step(index)
        compare(env, branch, max_actions)
    finally:
        env.snapshot_free(snap)
        branch.close()


def inference(agent, env, refs, payments):
    with torch.no_grad():
        logits = agent._forward_logits(env._get_obs(), refs, payments, len(refs))
    if logits.numel() != len(refs) or not torch.isfinite(logits).all():
        raise AssertionError('actual DMC inference has wrong shape/nonfinite logits')
