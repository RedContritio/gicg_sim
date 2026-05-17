"""WP / CI95 / Wilson statistics — shared by eval reports.

Pure numpy/math helpers — no torch / no env dependencies."""

from __future__ import annotations

import math
from typing import Tuple


Z95 = 1.959963984540054  # two-sided 95% normal z


def wp_ci95(wins: int, n_games: int) -> Tuple[float, float, float]:
    """Win-probability mean + Wald 95% CI.

    Returns (wp_mean, ci_lo, ci_hi). For small n,prefer ``wilson_ci``.
    Raises if n_games < 1."""
    if n_games < 1:
        raise ValueError(f'wp_ci95: n_games={n_games} < 1')
    p = wins / n_games
    se = math.sqrt(max(p * (1 - p) / n_games, 0.0))
    lo = max(0.0, p - Z95 * se)
    hi = min(1.0, p + Z95 * se)
    return p, lo, hi


def wilson_ci(wins: int, n_games: int, z: float = Z95) -> Tuple[float, float]:
    """Wilson score interval (better for small n / boundary p).

    Returns (ci_lo, ci_hi)."""
    if n_games < 1:
        raise ValueError(f'wilson_ci: n_games={n_games} < 1')
    p = wins / n_games
    z2 = z * z
    denom = 1 + z2 / n_games
    centre = (p + z2 / (2 * n_games)) / denom
    half = (z * math.sqrt(p * (1 - p) / n_games + z2 / (4 * n_games * n_games))) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def swap_sides_wp(wins_p0: int, n_p0: int, wins_p1: int, n_p1: int) -> Tuple[float, float, float]:
    """Symmetric WP over swap-sides protocol. Returns (mean, p0_wp, p1_wp).

    p0_wp = wins as P0 / games as P0; p1_wp = wins as P1 / games as P1;
    mean is the n-weighted average."""
    if n_p0 < 1 or n_p1 < 1:
        raise ValueError(f'swap_sides_wp: n_p0={n_p0} n_p1={n_p1} both must be ≥ 1')
    wp_p0 = wins_p0 / n_p0
    wp_p1 = wins_p1 / n_p1
    mean = (wins_p0 + wins_p1) / (n_p0 + n_p1)
    return mean, wp_p0, wp_p1
