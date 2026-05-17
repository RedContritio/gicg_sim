"""Scenario + obs config — shared by AZ / CFR / DMC.

Migrated from training.az.config per review B.4 (ADR-0006 layout 合规:
az ⟷ cfr 零互 import + framework 不依赖 algorithm-specific module)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ObsConfig:
    """Per-game obs assembly + shuffle toggles."""

    schema_version: int = 2
    include_char_skill_refs: bool = True
    shuffle_counters: bool = True
    shuffle_hooks: bool = True
    shuffle_cards: bool = True
    shuffle_skill_slots: bool = True

    def to_engine_json(self) -> dict:
        return {
            'include_char_skill_refs': self.include_char_skill_refs,
            'shuffle_counters': self.shuffle_counters,
            'shuffle_hooks': self.shuffle_hooks,
            'shuffle_cards': self.shuffle_cards,
            'shuffle_skill_slots': self.shuffle_skill_slots,
        }


@dataclass
class ScenarioConfig:
    """Which game to play during self-play and eval."""

    team_0: list[str]
    team_1: list[str]
    card_pool: Optional[list[str]] = None
    data_dir: Optional[str] = None

    char_pool: Optional[list[str]] = None
    team_size: int = 1
    disjoint_teams: bool = False

    # Curriculum env knobs (forwarded to GicgEnv). 0 / None preserve
    # legacy behavior: unbounded rounds, random dice roll each round,
    # fully observable. See docs/3_plans/curriculum/plan.md Stage 0/1/2.
    max_rounds: int = 0
    fix_dice: Optional[list[int]] = None
    obs_mask: Optional[list[str]] = None
    # ADR-0011: deck padding spec, e.g. {"card": "碌碌无为", "target_size": 15}.
    # None = deck length equals eligible-card count (no padding). Existing
    # cfgs that previously relied on the engine-level "碌碌无为" hardcode
    # set this explicitly to preserve their pre-ADR-0011 deck shape.
    deck_padding: Optional[dict] = None
    # ADR-0011: pool ID(s) under data/pools/. None = engine default
    # (["v_legacy"]). Accepts a single str or a list[str] for sibling
    # pool union; see GicgEnv `pool` for semantics.
    pool: Optional[object] = None

    def __post_init__(self):
        if self.char_pool is not None:
            if len(self.team_0) != self.team_size:
                raise ValueError(
                    f'random mode: len(team_0)={len(self.team_0)} must '
                    f'equal team_size={self.team_size} so eval matches '
                    f'the training distribution'
                )
            if len(self.team_1) != self.team_size:
                raise ValueError(f'random mode: len(team_1)={len(self.team_1)} must equal team_size={self.team_size}')
            if len(set(self.team_0)) != len(self.team_0):
                raise ValueError(
                    f'random mode: team_0={self.team_0} has duplicate characters — within-team uniqueness required'
                )
            if len(set(self.team_1)) != len(self.team_1):
                raise ValueError(
                    f'random mode: team_1={self.team_1} has duplicate characters — within-team uniqueness required'
                )
            pool_set = set(self.char_pool)
            t0_extra = set(self.team_0) - pool_set
            if t0_extra:
                raise ValueError(f'random mode: team_0 contains chars not in char_pool: {sorted(t0_extra)}')
            t1_extra = set(self.team_1) - pool_set
            if t1_extra:
                raise ValueError(f'random mode: team_1 contains chars not in char_pool: {sorted(t1_extra)}')
            if self.team_size > len(self.char_pool):
                raise ValueError(
                    f'random mode: team_size={self.team_size} exceeds char_pool size {len(self.char_pool)}'
                )

    def sample_teams(self, rng) -> tuple[list[str], list[str]]:
        """Return (team_0, team_1) for one self-play game."""
        if self.char_pool is None:
            return list(self.team_0), list(self.team_1)
        if self.team_size > len(self.char_pool):
            raise ValueError(f'team_size={self.team_size} exceeds char_pool size {len(self.char_pool)}')
        t0 = rng.sample(self.char_pool, self.team_size)
        if self.disjoint_teams:
            remaining = [c for c in self.char_pool if c not in t0]
            if len(remaining) < self.team_size:
                raise ValueError(
                    f'disjoint_teams: char_pool={self.char_pool} too small (need {2 * self.team_size} distinct chars)'
                )
            t1 = rng.sample(remaining, self.team_size)
            return t0, t1
        return t0, rng.sample(self.char_pool, self.team_size)
