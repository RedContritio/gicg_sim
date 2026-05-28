"""Sync rollout helpers — _eval_leaf / _puct_select / _find_action_index
/ _random_rollout_value / _apply_leaf_mixing. The single-rollout driver
loop ``run_rollout`` lives in ``run_rollout.py`` so this file stays
below the line-limit."""

from __future__ import annotations

import math
import random

from gicg_env.env import _terminal_z

from .action_id import ActionId, legal_ids_from_env
from .config import MCTSConfig
from .node import MCTSNode


def _eval_leaf(node: MCTSNode, env, evaluator, legal_ids: list[ActionId]) -> None:
    """Run network on the current env state, populate children with
    priors from the network output, cache the P0-perspective leaf
    value on the node."""
    if len(legal_ids) == 0:
        raise RuntimeError('MCTS _eval_leaf: env reports 0 legal actions at a non-terminal state — engine deadlock')
    refs = env.get_action_refs()
    payments = env.get_legal_action_payments()
    dyn = env._get_obs()

    prior_array, v_acting = evaluator.eval_state(dyn, refs, payments)
    v_p0 = v_acting if node.turn == 0 else -v_acting
    node.leaf_value_p0 = v_p0

    for i, aid in enumerate(legal_ids):
        if aid in node.children:
            continue
        node.children[aid] = MCTSNode(
            turn=-1,
            terminal=False,
            prior=float(prior_array[i]),
        )
    node.expanded = True


def _puct_select(parent: MCTSNode, legal_ids: list[ActionId], c_puct: float) -> ActionId:
    """PUCT over the currently-legal children of parent."""
    if not legal_ids:
        raise RuntimeError('PUCT called with empty legal_ids')

    best_id = None
    best_score = -math.inf
    for aid in legal_ids:
        child = parent.children.get(aid)
        if child is None:
            raise RuntimeError(
                f'PUCT: legal action {aid} has no child in parent — '
                'expansion and legal-set discovery must happen before '
                'selection'
            )
        total_n = child.N + child.N_virtual
        q_p0 = child.q_p0()
        q = q_p0 if parent.turn == 0 else -q_p0
        u = c_puct * child.prior * math.sqrt(child.N_avail) / (1 + total_n)
        score = q + u
        if best_id is None or score > best_score or (score == best_score and aid < best_id):
            best_id = aid
            best_score = score
    return best_id


def _find_action_index(legal_ids: list[ActionId], target: ActionId) -> int:
    """Locate target's position in the current legal list."""
    for i, aid in enumerate(legal_ids):
        if aid == target:
            return i
    raise RuntimeError(f'MCTS: chosen action {target} not found in current legal list')


def _random_rollout_value(
    env,
    max_depth: int,
    rng: random.Random,
) -> tuple[float, int]:
    """Play out from the current env state with uniformly-random
    actions until terminal or max_depth. Delegates to the Go-side
    random_rollout for speed."""
    seed = rng.getrandbits(64)
    winner, steps = env.random_rollout(seed=seed, max_steps=max_depth)
    if winner < 0:
        return 0.0, steps
    return _terminal_z(winner), steps


def _apply_leaf_mixing(
    node: MCTSNode,
    legal_ids: list[ActionId],
    config: MCTSConfig,
    rollout_v_p0,
) -> None:
    """Blend network value/prior with search-independent baselines."""
    if rollout_v_p0 is not None and config.value_mix_lambda < 1.0:
        net_v = node.leaf_value_p0 if node.leaf_value_p0 is not None else 0.0
        lam = config.value_mix_lambda
        node.leaf_value_p0 = lam * net_v + (1.0 - lam) * rollout_v_p0
    if config.prior_mix_lambda < 1.0 and legal_ids:
        n = len(legal_ids)
        uniform = 1.0 / n
        plam = config.prior_mix_lambda
        for aid in legal_ids:
            if aid in node.children:
                child = node.children[aid]
                child.prior = plam * child.prior + (1.0 - plam) * uniform


# Import and re-export run_rollout as _rollout for API compat.
from .run_rollout import run_rollout as _rollout  # noqa: E402, F401
