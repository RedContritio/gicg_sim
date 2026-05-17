"""RunResult dataclass — what ``train_az`` returns.

Phase 2-ζ (FU-W4-AZ-rewrite, T2.ζ) — inlined from
``training.paradigms.az.legacy.train_loop.run_result``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from training.paradigms.az.arena import ArenaResult


@dataclass
class RunResult:
    """Captures everything the smoke test needs to verify without
    having to parse files."""

    n_games_played: int
    training_stats: list[dict] = field(default_factory=list)
    arena_results: list[tuple[int, ArenaResult]] = field(default_factory=list)
    # Gauntlet is now dispatched async to eval_service; results are
    # written directly to gauntlet_results.jsonl. Kept as legacy API
    # (always empty in the new flow) for the smoke test contract.
    gauntlet_results: list[tuple[int, dict]] = field(default_factory=list)
    champion_replacements: list[int] = field(default_factory=list)
    selfplay_winners: list[int] = field(default_factory=list)
    selfplay_n_steps: list[int] = field(default_factory=list)
    artifacts_dir: Optional[str] = None
