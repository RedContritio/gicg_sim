"""Utility functions used by both search entries + by outside callers."""

from __future__ import annotations

import random

import numpy as np

from .action_id import ActionId
from .config import MCTSConfig
from .node import MCTSNode


def rng_dirichlet(rng: random.Random, alpha: float, n: int) -> np.ndarray:
    """Dirichlet draw seeded from stdlib Random."""
    seed = rng.randint(0, 2**63 - 1)
    np_rng = np.random.default_rng(seed)
    return np_rng.dirichlet([alpha] * n)


def _argmax_visits(root: MCTSNode) -> ActionId:
    """Return the root child with the highest visit count."""
    best_id = None
    best_n = -1
    for aid, child in root.children.items():
        if child.N > best_n or (child.N == best_n and (best_id is None or aid < best_id)):
            best_id = aid
            best_n = child.N
    if best_id is None:
        raise RuntimeError('_argmax_visits: root has no children')
    return best_id


def _pick_action_from_visits(
    visit_arr: np.ndarray,
    n_legal: int,
    config: MCTSConfig,
    game_step: int,
    rng: random.Random,
) -> tuple[int, np.ndarray]:
    """Temperature-sampled action picker."""
    if n_legal == 0:
        raise RuntimeError('_pick_action_from_visits: n_legal == 0')

    if game_step < config.temperature_switch_step and config.temperature > 0:
        tau = config.temperature
        weights = visit_arr ** (1.0 / tau)
        total = float(weights.sum())
        if total == 0.0:
            raise RuntimeError('Temperature sampling: all visits are zero — MCTS produced no statistics to sample from')
        pi = weights / total
        chosen = rng.choices(range(n_legal), weights=list(pi))[0]
    else:
        chosen = int(visit_arr.argmax())
        pi = np.zeros(n_legal, dtype=np.float32)
        pi[chosen] = 1.0
    return chosen, pi


def _detect_discovery(
    checkpoints: dict[int, ActionId],
    discovery_order: tuple,
) -> list[int]:
    """Detect combo-discovery events in the visit trajectory."""
    if len(checkpoints) < 2:
        return []
    sorted_rollouts = sorted(checkpoints.keys())
    early = sorted_rollouts[0]
    final = sorted_rollouts[-1]
    if len(sorted_rollouts) >= 3:
        mid = sorted_rollouts[-2]
    else:
        mid = final

    if checkpoints[early] != checkpoints[final] and checkpoints[mid] == checkpoints[final]:
        return [final]
    return []
