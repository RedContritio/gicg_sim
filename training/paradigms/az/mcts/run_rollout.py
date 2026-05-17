"""Sync rollout driver — one rollout from the expanded root."""

from __future__ import annotations

import random
import time as _time
from typing import Optional

from gicg_env.env import _terminal_z

from .action_id import legal_ids_from_env
from .config import MCTSConfig, MCTSProfile
from .node import MCTSNode
from .rollout import (
    _apply_leaf_mixing,
    _eval_leaf,
    _find_action_index,
    _puct_select,
    _random_rollout_value,
)


def run_rollout(
    root: MCTSNode,
    env,
    evaluator,
    config: MCTSConfig,
    rng: random.Random,
    prof: Optional[MCTSProfile] = None,
) -> None:
    """One rollout: descend from the root, step env, backup leaf value."""
    do_profile = prof is not None
    _pc = _time.perf_counter
    path: list[MCTSNode] = [root]
    depth = 0

    while True:
        node = path[-1]
        if node.terminal:
            break

        if do_profile:
            t0 = _pc()
        legal_ids = legal_ids_from_env(env)
        if do_profile:
            prof.n_env_query += 1
            prof.env_query_s += _pc() - t0
        if not legal_ids:
            raise RuntimeError(f'MCTS rollout: non-terminal env has 0 legal actions at depth {depth} — engine deadlock')

        if not node.expanded:
            if do_profile:
                t0 = _pc()
            _eval_leaf(node, env, evaluator, legal_ids)
            if do_profile:
                prof.n_eval += 1
                prof.eval_s += _pc() - t0
            rollout_v = None
            if config.value_mix_lambda < 1.0:
                if do_profile:
                    t0 = _pc()
                rollout_v, r_steps = _random_rollout_value(
                    env,
                    config.max_rollout_depth - depth,
                    rng,
                )
                if do_profile:
                    prof.n_rollout += 1
                    prof.n_rollout_steps += r_steps
                    prof.rollout_s += _pc() - t0
            _apply_leaf_mixing(node, legal_ids, config, rollout_v)
            break

        need_reeval = any(aid not in node.children for aid in legal_ids)
        if need_reeval:
            if do_profile:
                t0 = _pc()
            _eval_leaf(node, env, evaluator, legal_ids)
            if do_profile:
                prof.n_eval += 1
                prof.eval_s += _pc() - t0

        for aid in legal_ids:
            node.children[aid].N_avail += 1

        chosen_id = _puct_select(node, legal_ids, config.c_puct)
        action_idx = _find_action_index(legal_ids, chosen_id)

        if do_profile:
            t0 = _pc()
        _, _, done, info = env.step(action_idx)
        if do_profile:
            prof.n_env_step += 1
            prof.env_step_s += _pc() - t0
        if info.get('need_target'):
            raise RuntimeError(
                'MCTS rollout hit STEP_NEED_TARGET — legacy PendingCardTarget path is unsupported by the tree.'
            )

        child = node.children[chosen_id]
        child.turn = env.acting_player
        child.terminal = bool(done)
        if done:
            child.winner = int(info.get('winner', -1))
            child.leaf_value_p0 = _terminal_z(child.winner)
            child.expanded = True

        path.append(child)
        depth += 1

        if depth > config.max_rollout_depth:
            raise RuntimeError(f'MCTS rollout exceeded max_rollout_depth={config.max_rollout_depth} at depth {depth}.')

    leaf = path[-1]
    if leaf.leaf_value_p0 is None:
        raise RuntimeError('MCTS rollout: leaf has no cached P0 value — expansion bug')
    leaf_v = leaf.leaf_value_p0
    for node in path:
        node.N += 1
        node.W += leaf_v
