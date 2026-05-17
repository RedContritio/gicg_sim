"""Traversal-side config + per-decision record + stats dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TraversalConfig:
    max_game_steps: int = 400
    # ε-exploration: sampling distribution mixes ε*uniform + (1-ε)*σ
    epsilon: float = 0.1
    # Cap per-node importance weight contribution.
    importance_weight_max: float = 100.0
    # "os" → outcome sampling MCCFR (production default, TCG-viable).
    # "es" → external sampling MCCFR (Kuhn-class only; TCG-infeasible
    #        due to exponential branch explosion).
    sampling_mode: str = 'os'


@dataclass
class _RecordedDecision:
    """One decision point on the sampled traversal path."""

    is_traverser: bool
    acting_player: int
    game_id: int
    dynamic: dict
    policy: 'object'  # np.ndarray
    sampled_action: int
    q_sampled: float
    reach_opp_pre: float
    reach_q_prefix: float


@dataclass
class TraversalStats:
    n_steps: int = 0
    n_traverser_decisions: int = 0
    n_opponent_decisions: int = 0
    advantage_adds: int = 0
    strategy_adds: int = 0
    value_adds: int = 0
    outcome_traverser: float = 0.0
