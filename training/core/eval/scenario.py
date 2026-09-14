"""Scenario sampling and deterministic seed helpers for evaluation."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from training.core.config.base import ScenarioCfg


class ScenarioFactory:
    """Wraps ``ScenarioCfg`` + master seed to produce per-game seeds
    and team samples for both actor and eval."""

    def __init__(self, scenario: ScenarioCfg, master_seed: int) -> None:
        self.scenario = scenario
        self.master_seed = master_seed
        self._rng = random.Random(master_seed)

    def derive_game_seed(self, game_idx: int, prefix: str = 'game') -> int:
        """Deterministic per-game seed via blake2s. Same idx + prefix →
        same seed across runs (reproducibility)."""
        h = hashlib.blake2s(f'{prefix}/{game_idx}'.encode(), digest_size=4).digest()
        return (self.master_seed ^ int.from_bytes(h, 'big')) & 0x7FFFFFFF

    def sample_teams(self) -> tuple:
        """Return (team_0, team_1) honoring char_pool / disjoint_teams.

        For non-random scenarios returns the fixed team lists."""
        sc = self.scenario
        if sc.char_pool is None:
            return list(sc.team_0), list(sc.team_1)
        if sc.team_size > len(sc.char_pool):
            raise ValueError(f'sample_teams: team_size={sc.team_size} > char_pool={len(sc.char_pool)}')
        t0 = self._rng.sample(sc.char_pool, sc.team_size)
        if sc.disjoint_teams:
            remaining = [c for c in sc.char_pool if c not in t0]
            if len(remaining) < sc.team_size:
                raise ValueError('sample_teams: disjoint_teams pool too small')
            t1 = self._rng.sample(remaining, sc.team_size)
            return t0, t1
        return t0, self._rng.sample(sc.char_pool, sc.team_size)


def eval_seed_pool(master_seed: int, n_games: int, prefix: str = 'eval') -> list:
    """Generate ``n_games`` deterministic seeds for an eval batch.
    Each entry is reproducible via (master_seed, game_idx, prefix)."""
    out: list = []
    for i in range(n_games):
        h = hashlib.blake2s(f'{prefix}/{i}'.encode(), digest_size=4).digest()
        out.append((master_seed ^ int.from_bytes(h, 'big')) & 0x7FFFFFFF)
    return out
