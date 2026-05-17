"""MCTSNode — one state node in the IS-UCT tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MCTSNode:
    """One state node in the IS-UCT tree.

    Statistics are from the perspective of P0 throughout the tree;
    PUCT selection flips to the parent's turn at query time.
    """

    turn: int
    terminal: bool
    winner: int = -1

    prior: float = 0.0
    N: int = 0
    W: float = 0.0
    N_avail: int = 0
    N_virtual: int = 0

    expanded: bool = False
    leaf_value_p0: Optional[float] = None
    children: dict = field(default_factory=dict)

    def q_p0(self) -> float:
        total = self.N + self.N_virtual
        if total == 0:
            return 0.0
        return self.W / total
