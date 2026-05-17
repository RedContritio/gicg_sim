"""Matchup helpers — swap-sides protocol + result aggregation.

Spec ref: eval-protocol/spec.md."""

from __future__ import annotations

from typing import List

from training.core.eval.job import EvalReport, EvalResult
from training.core.eval.statistics import swap_sides_wp, wilson_ci


def aggregate_results(opponent_id: str, results: List[EvalResult]) -> EvalReport:
    """Aggregate per-game results → EvalReport (swap-sides aware).

    Counts our-side wins for each starting player slot separately to
    surface side-imbalance. CI95 from Wilson score interval."""
    if not results:
        raise ValueError('aggregate_results: empty results list')

    wins_p0 = 0
    n_p0 = 0
    wins_p1 = 0
    n_p1 = 0
    total_len = 0
    for r in results:
        won = r.winner == r.our_player
        if r.our_player == 0:
            n_p0 += 1
            wins_p0 += int(won)
        else:
            n_p1 += 1
            wins_p1 += int(won)
        total_len += r.length

    n_total = n_p0 + n_p1
    if n_p0 == 0 or n_p1 == 0:
        # Single-side protocol — fall back to plain WP.
        if n_p0 == 0:
            wp_mean = wins_p1 / max(n_p1, 1)
            ci_lo, ci_hi = wilson_ci(wins_p1, max(n_p1, 1))
            wp_p0 = 0.0
            wp_p1 = wp_mean
        else:
            wp_mean = wins_p0 / max(n_p0, 1)
            ci_lo, ci_hi = wilson_ci(wins_p0, max(n_p0, 1))
            wp_p0 = wp_mean
            wp_p1 = 0.0
    else:
        wp_mean, wp_p0, wp_p1 = swap_sides_wp(wins_p0, n_p0, wins_p1, n_p1)
        ci_lo, ci_hi = wilson_ci(wins_p0 + wins_p1, n_total)

    return EvalReport(
        opponent_id=opponent_id,
        n_games=n_total,
        wp_mean=wp_mean,
        wp_swap_p0=wp_p0,
        wp_swap_p1=wp_p1,
        ci95_lo=ci_lo,
        ci95_hi=ci_hi,
        avg_length=total_len / max(n_total, 1),
    )
