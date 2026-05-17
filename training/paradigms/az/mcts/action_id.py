"""Action identity — the MCTS tree key.

See the docstring on ActionId below for the 6-tuple layout. Stays
stable across determinizations: two rollouts observing the same
logical action produce the same ActionId, so tree children survive
per-rollout re-sampling of opponent hidden state."""

from __future__ import annotations

import numpy as np

# Must match gicg_engine/types.go ActionKind. ACTION_TUNE isn't in
# framework.obs_constants (the network doesn't dispatch on it yet)
# so define it locally here where the tree needs to reason about it.
ACTION_TUNE = 4


#: Canonical MCTS identity tuple for a legal action.
ActionId = tuple


def build_action_id(identity_row: np.ndarray, payment_row: np.ndarray) -> ActionId:
    """Assemble one ActionId from a row of the (n_legal, 5) identities
    array and a row of the (n_legal, 8) payments array."""
    return (
        int(identity_row[0]),
        int(identity_row[1]),
        int(identity_row[2]),
        int(identity_row[3]),
        int(identity_row[4]),
        tuple(int(x) for x in payment_row),
    )


def legal_ids_from_env(env) -> list[ActionId]:
    """Read the current env's legal action list and return each
    action's MCTS identity."""
    ids = env.get_action_identities()
    pays = env.get_legal_action_payments()
    return [build_action_id(ids[i], pays[i]) for i in range(ids.shape[0])]
