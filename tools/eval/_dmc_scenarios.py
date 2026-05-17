"""Generate fixed-seed eval scenarios for DMC periodic eval.

Each scenario fully determines a game:
- teams (sampled if char_pool given, else fixed cfg.team_0/team_1)
- env seed (controls dice + deck shuffle + initial hand)

DMC eval protocol per decision #8:
- Pre-generated set of N scenarios used for all eval rounds
- Each scenario played twice (swap_sides) per baseline
- Reproducible across training runs.

Relocated from ``training/paradigms/dmc/legacy/eval/gen_eval_scenarios.py``
(FU-W4-DMC-pt2) alongside the evaluator/replay runner it feeds.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class EvalScenario:
    """One fixed eval scenario.

    Review D.5 (2026-05-14): 3-axis seeds. env_seed = dice + DSL randomness
    + obs perm (same as before). deck_seed_p0 / deck_seed_p1 independently
    control per-player deck Fisher-Yates shuffle, enabling 'team 同 deck 不同'
    ablation. Defaults None → fall back to env_seed (backward compat)."""

    scenario_id: int
    team_0: list[str]
    team_1: list[str]
    env_seed: int
    deck_seed_p0: Optional[int] = None
    deck_seed_p1: Optional[int] = None


def generate_eval_scenarios(
    seed: int,
    n: int,
    team_0: list[str],
    team_1: list[str],
    char_pool: Optional[list[str]] = None,
    team_size: int = 1,
    disjoint_teams: bool = False,
) -> list[EvalScenario]:
    """Generate n eval scenarios with fixed seed.

    If ``char_pool`` is set, randomly sample team_0 / team_1 per
    scenario (asymmetric matchup,见 decision #5 Stage 4 spec).
    Otherwise use fixed team_0 / team_1 (Stage 3 spec).
    """
    rng = random.Random(seed)
    scenarios: list[EvalScenario] = []
    for i in range(n):
        if char_pool is None:
            t0 = list(team_0)
            t1 = list(team_1)
        else:
            t0 = rng.sample(char_pool, team_size)
            if disjoint_teams:
                remaining = [c for c in char_pool if c not in t0]
                t1 = rng.sample(remaining, team_size)
            else:
                t1 = rng.sample(char_pool, team_size)
        scenarios.append(
            EvalScenario(
                scenario_id=i,
                team_0=t0,
                team_1=t1,
                env_seed=rng.randint(0, 2**31 - 1),
                # D.5: independent deck seeds — let "team 同 deck 不同" ablation
                # vary hand-draw RNG without re-rolling dice.
                deck_seed_p0=rng.randint(0, 2**31 - 1),
                deck_seed_p1=rng.randint(0, 2**31 - 1),
            )
        )
    return scenarios


def scenarios_to_dicts(scenarios: list[EvalScenario]) -> list[dict]:
    return [asdict(s) for s in scenarios]
