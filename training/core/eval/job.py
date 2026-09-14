"""EvalJob / EvalReport / EvalResult dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EvalJob:
    """One eval task — opponent + N scenarios."""

    opponent_id: str
    n_games: int
    snapshot_tag: str = 'snapshot_eval'
    starting_player_alternates: bool = True
    seed_base: int = 0


@dataclass(frozen=True)
class EvalResult:
    """One eval game's outcome."""

    job_id: str
    game_idx: int
    winner: int
    our_player: int
    length: int
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EvalReport:
    """Aggregated stats over all games of an EvalJob."""

    opponent_id: str
    n_games: int
    wp_mean: float
    wp_swap_p0: float
    wp_swap_p1: float
    ci95_lo: float
    ci95_hi: float
    avg_length: float
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OpponentSpec:
    """Serializable description that callers can map to a registry entry.

    ``kind`` + ``params`` together identify a unique opponent. Used by
    actor and evaluation configuration; ``OpponentRegistry`` itself resolves
    names through ``get(name, seed, params)``."""

    kind: str
    params: dict = field(default_factory=dict)
    name: Optional[str] = None
