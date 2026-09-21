"""Parallel (async) rollout path — _InFlightRollout holder + phased
descent (_descend_with_vl) and commit (_commit_parallel_rollout)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from gicg_env.env import _terminal_z

from .action_id import legal_ids_from_env
from .config import MCTSConfig
from .node import MCTSNode
from .rollout import (
    _apply_leaf_mixing,
    _find_action_index,
    _puct_select,
)

if TYPE_CHECKING:
    import numpy as np


_VL_AMOUNT = 1  # one virtual visit per in-flight rollout


@dataclass
class _InFlightRollout:
    """Bookkeeping for one descent that's waiting on an eval result."""

    path: list
    leaf_legal_ids: list
    rollout_v_p0: Optional[float] = None


def _descend_with_vl(
    root: MCTSNode,
    env,
    config: MCTSConfig,
) -> tuple[_InFlightRollout, Optional[tuple]]:
    """Descend from the already-expanded root, applying virtual loss
    on each chosen edge. Stops at a terminal node or the first
    unexpanded (leaf) node."""
    path: list[MCTSNode] = [root]
    depth = 0

    while True:
        node = path[-1]
        if node.terminal:
            return _InFlightRollout(path=path, leaf_legal_ids=[]), None

        legal_ids = legal_ids_from_env(env)
        if not legal_ids:
            raise RuntimeError(f'MCTS rollout: non-terminal env has 0 legal actions at depth {depth} — engine deadlock')

        if not node.expanded:
            refs = env.get_action_refs()
            payments = env.get_legal_action_payments()
            dyn = env._get_obs()
            return (
                _InFlightRollout(path=path, leaf_legal_ids=legal_ids),
                (dyn, refs, payments),
            )

        for aid in legal_ids:
            if aid not in node.children:
                node.children[aid] = MCTSNode(
                    turn=-1,
                    terminal=False,
                    prior=1.0 / float(len(legal_ids)),
                )
            node.children[aid].N_avail += 1

        chosen_id = _puct_select(node, legal_ids, config.c_puct)
        action_idx = _find_action_index(legal_ids, chosen_id)

        child = node.children[chosen_id]
        child.N_virtual += _VL_AMOUNT

        _, _, done, info = env.step(action_idx)
        if info.get('need_target'):
            # Pending target / forced-switch continuation — see
            # run_rollout.py. Child stays non-terminal; the suspended
            # rollout resumes at the target choices next iteration.
            child.turn = env.acting_player
            child.terminal = False
            path.append(child)
            depth += 1
            if depth > config.max_rollout_depth:
                raise RuntimeError(
                    f'MCTS rollout exceeded max_rollout_depth={config.max_rollout_depth} at depth {depth}.'
                )
            continue

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


def _commit_parallel_rollout(
    in_flight: _InFlightRollout,
    prior: 'Optional[np.ndarray]',
    value: Optional[float],
    config: Optional[MCTSConfig] = None,
) -> None:
    """Apply the eval result for one in-flight rollout."""
    path = in_flight.path
    leaf = path[-1]

    if leaf.terminal:
        leaf_v_p0 = leaf.leaf_value_p0
    else:
        if prior is None or value is None:
            raise RuntimeError('_commit_parallel_rollout: non-terminal leaf needs prior/value')
        legal_ids = in_flight.leaf_legal_ids
        if len(legal_ids) == 0:
            raise RuntimeError('_commit_parallel_rollout: non-terminal leaf has no legal_ids')
        if len(prior) != len(legal_ids):
            raise RuntimeError(
                f'_commit_parallel_rollout: prior length {len(prior)} does not match legal count {len(legal_ids)}'
            )
        for i, aid in enumerate(legal_ids):
            if aid not in leaf.children:
                leaf.children[aid] = MCTSNode(
                    turn=-1,
                    terminal=False,
                    prior=float(prior[i]),
                )
            else:
                if leaf.children[aid].N == 0 and leaf.children[aid].N_virtual == 0 and not leaf.children[aid].expanded:
                    leaf.children[aid].prior = float(prior[i])
        leaf_v_acting = float(value)
        leaf_v_p0 = leaf_v_acting if leaf.turn == 0 else -leaf_v_acting
        leaf.leaf_value_p0 = leaf_v_p0
        leaf.expanded = True
        if config is not None:
            _apply_leaf_mixing(
                leaf,
                legal_ids,
                config,
                in_flight.rollout_v_p0,
            )

    leaf_v_final = leaf.leaf_value_p0 if leaf.leaf_value_p0 is not None else 0.0
    for node in path:
        node.N += 1
        node.W += leaf_v_final

    for i in range(1, len(path)):
        path[i].N_virtual -= _VL_AMOUNT
