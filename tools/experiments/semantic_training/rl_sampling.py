"""Decision-stratified sampling for semantic terminal-reward updates."""

from __future__ import annotations

import math


def stratified_indices(rows, rng, reroll_fraction: float) -> list[int]:
    if not 0 < reroll_fraction < 1:
        raise ValueError('reroll_fraction must be between zero and one')
    reroll = [index for index, row in enumerate(rows) if row.get('decision_type') == 'reroll']
    ordinary = [index for index, row in enumerate(rows) if row.get('decision_type') != 'reroll']
    if not reroll or not ordinary:
        selected = list(range(len(rows)))
        rng.shuffle(selected)
        return selected
    total = min(
        len(rows),
        math.floor(len(reroll) / reroll_fraction + 1e-9),
        math.floor(len(ordinary) / (1 - reroll_fraction) + 1e-9),
    )
    reroll_count = min(len(reroll), max(1, round(total * reroll_fraction)))
    ordinary_count = min(len(ordinary), total - reroll_count)
    reroll_count = min(len(reroll), total - ordinary_count)
    rng.shuffle(reroll)
    rng.shuffle(ordinary)
    selected = reroll[:reroll_count] + ordinary[:ordinary_count]
    rng.shuffle(selected)
    return selected
