"""Explicit sampled training teams and balanced disjoint 2v2 evaluation cases."""

from dataclasses import replace
from itertools import combinations, combinations_with_replacement
import random

from training.core.episode_seeds import derive_seed
from training.paradigms.dmc._eval_scenarios import EvalScenario, generate_eval_scenarios


def with_teams(cfg, team_0, team_1):
    return replace(cfg, scenario=replace(cfg.scenario, team_0=list(team_0), team_1=list(team_1)))


def sample_config(cfg, seed):
    s = cfg.scenario
    if s.char_pool is None:
        return cfg
    rng = random.Random(derive_seed(seed, 'teams'))
    a = rng.sample(s.char_pool, s.team_size)
    available = [c for c in s.char_pool if c not in a] if s.disjoint_teams else s.char_pool
    b = rng.sample(available, s.team_size)
    return with_teams(cfg, a, b)


def matchup_key(a, b):
    return ' / '.join(sorted(['+'.join(sorted(a)), '+'.join(sorted(b))]))


def eval_cases(cfg, seed, n):
    s = cfg.scenario
    if s.char_pool is None:
        return generate_eval_scenarios(seed, n, s.team_0, s.team_1)
    teams = list(combinations(s.char_pool, s.team_size))
    pairs = (
        [(a, b) for a, b in combinations(teams, 2) if not set(a) & set(b)]
        if s.disjoint_teams
        else list(combinations_with_replacement(teams, 2))
    )
    if not pairs or n <= 0 or n % len(pairs):
        raise ValueError(f'evaluation scenario count must be a positive multiple of {len(pairs)}')
    rng = random.Random(derive_seed(seed, 'eval-teams'))
    cases = []
    for i in range(n):
        a, b = map(list, pairs[i % len(pairs)])
        rng.shuffle(a)
        rng.shuffle(b)
        if rng.randrange(2):
            a, b = b, a
        cases.append(
            EvalScenario(
                i,
                a,
                b,
                derive_seed(seed, 'eval-game', i),
                derive_seed(seed, 'eval-deck0', i),
                derive_seed(seed, 'eval-deck1', i),
            )
        )
    return cases
