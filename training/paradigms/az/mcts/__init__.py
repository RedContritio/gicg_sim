"""IS-UCT Monte Carlo Tree Search for GICG self-play — public API."""

from __future__ import annotations

from .action_id import (
    ACTION_TUNE,
    ActionId,
    build_action_id,
    legal_ids_from_env,
)
from .config import (
    MCTSConfig,
    MCTSProfile,
    compute_annealed_lambda,
)
from .node import MCTSNode
from .parallel import (
    _InFlightRollout,
    _commit_parallel_rollout,
    _descend_with_vl,
)
from .rollout import (
    _apply_leaf_mixing,
    _eval_leaf,
    _find_action_index,
    _puct_select,
    _random_rollout_value,
)
from .search import mcts_search, mcts_search_parallel
from .utils import (
    _argmax_visits,
    _detect_discovery,
    _pick_action_from_visits,
    rng_dirichlet,
)


__all__ = [
    'ACTION_TUNE',
    'ActionId',
    'MCTSConfig',
    'MCTSNode',
    'MCTSProfile',
    'build_action_id',
    'compute_annealed_lambda',
    'legal_ids_from_env',
    'mcts_search',
    'mcts_search_parallel',
    'rng_dirichlet',
    '_apply_leaf_mixing',
    '_argmax_visits',
    '_commit_parallel_rollout',
    '_descend_with_vl',
    '_detect_discovery',
    '_eval_leaf',
    '_find_action_index',
    '_InFlightRollout',
    '_pick_action_from_visits',
    '_puct_select',
    '_random_rollout_value',
]
