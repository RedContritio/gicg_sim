"""Profile the per-decision distribution of payment variants per identity.

T-A curriculum decision input: is it worth adding a factored
(identity, payment) action head? Only if typical decisions have many
payment variants sharing the same logical identity. If distribution is
~1 variant/identity, the engine-level dedup that already exists is
sufficient and T-A can be skipped for Stage 0.

Output per team setup:
- total legal-action count histogram
- unique-identity count histogram
- variants-per-identity distribution (how often an identity has k>1 payment variants)
- "wasteful" ratio = (legal - unique) / legal — fraction of raw actions
  that share an identity with another. 0 = no redundancy; 0.8 = 80% of
  raw actions are payment duplicates.

Run from repo root::

    .venv/bin/python -m tools.profile.profile_action_variants

Two default setups are probed: full 2v2 and Stage-0-style 1v1-no-cards.
Add --teams / --card-pool to probe custom configs.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from gicg_env import GicgEnv


@dataclass
class DecisionStats:
    n_decisions: int = 0
    total_legal: int = 0
    total_unique: int = 0
    legal_hist: Counter = field(default_factory=Counter)
    unique_hist: Counter = field(default_factory=Counter)
    # Per-identity payment-variant histogram across all decisions: how
    # many *distinct payment rows* were seen for each unique identity.
    variants_per_id_hist: Counter = field(default_factory=Counter)


def _record(stats: DecisionStats, identities: np.ndarray, payments: np.ndarray) -> None:
    """Add one decision's (identities, payments) to running stats."""
    n = identities.shape[0]
    if n == 0:
        return
    stats.n_decisions += 1
    stats.total_legal += n
    stats.legal_hist[n] += 1

    # Group by identity row tuple; count distinct payment rows within.
    buckets: dict[tuple, set] = {}
    for i in range(n):
        id_key = tuple(int(x) for x in identities[i])
        pay_key = tuple(int(x) for x in payments[i])
        buckets.setdefault(id_key, set()).add(pay_key)

    n_unique = len(buckets)
    stats.total_unique += n_unique
    stats.unique_hist[n_unique] += 1
    for variants in buckets.values():
        stats.variants_per_id_hist[len(variants)] += 1


def _sample(env: GicgEnv, rng: np.random.Generator, max_steps: int) -> DecisionStats:
    """Run one random self-play episode, accumulating per-decision stats."""
    stats = DecisionStats()
    for _ in range(max_steps):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            break
        # Only record on "real" action decisions (phase=action). Select-
        # active and need-target are trivially bounded and uninteresting
        # for the T-A decision.
        identities = env.get_action_identities()
        payments = env.get_legal_action_payments()
        _record(stats, identities, payments)

        a = int(rng.integers(0, len(kinds)))
        env.step(a)
    return stats


def _merge(a: DecisionStats, b: DecisionStats) -> DecisionStats:
    a.n_decisions += b.n_decisions
    a.total_legal += b.total_legal
    a.total_unique += b.total_unique
    a.legal_hist.update(b.legal_hist)
    a.unique_hist.update(b.unique_hist)
    a.variants_per_id_hist.update(b.variants_per_id_hist)
    return a


def _percentile(hist: Counter, q: float) -> int:
    """Return the smallest value v such that at least q-fraction of
    samples are ≤ v. ``hist`` maps value → count."""
    total = sum(hist.values())
    if total == 0:
        return 0
    target = q * total
    cum = 0
    for v in sorted(hist):
        cum += hist[v]
        if cum >= target:
            return v
    return max(hist)


def _print_stats(label: str, stats: DecisionStats) -> None:
    print(f'\n=== {label} ===')
    print(f'n_decisions      : {stats.n_decisions}')
    if stats.n_decisions == 0:
        return
    avg_legal = stats.total_legal / stats.n_decisions
    avg_unique = stats.total_unique / stats.n_decisions
    wasteful = 1.0 - (stats.total_unique / max(stats.total_legal, 1))
    print(f'avg legal-action : {avg_legal:.2f}')
    print(f'avg unique-ident : {avg_unique:.2f}')
    print(f'wasteful-fraction: {wasteful:.3f}  (0=no payment dup, 1=all dup)')
    print(
        f'legal p50/p90/p99: '
        f'{_percentile(stats.legal_hist, 0.5)} / '
        f'{_percentile(stats.legal_hist, 0.9)} / '
        f'{_percentile(stats.legal_hist, 0.99)}'
    )
    print(f'variants-per-identity distribution:')
    total = sum(stats.variants_per_id_hist.values())
    for k in sorted(stats.variants_per_id_hist):
        n = stats.variants_per_id_hist[k]
        frac = n / total
        bar = '#' * int(frac * 40)
        print(f'  {k:3d} variant(s): {n:7d}  ({frac * 100:5.2f}%)  {bar}')


def profile_setup(
    team_0: list[str],
    team_1: list[str],
    card_pool: list[str] | None,
    label: str,
    n_games: int,
    seed: int,
    max_rounds: int = 0,
) -> DecisionStats:
    total = DecisionStats()
    for i in range(n_games):
        rng = np.random.default_rng(seed + i)
        with GicgEnv(
            team_0,
            team_1,
            card_pool=card_pool,
            seed=seed + i,
            data_dir='data',
            max_rounds=max_rounds,
        ) as env:
            g_stats = _sample(env, rng, max_steps=600)
            _merge(total, g_stats)
    _print_stats(f'{label}  [n_games={n_games}]', total)
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--n-games', type=int, default=30)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()

    # Setup 1: full 2v2 — representative of production training.
    profile_setup(
        team_0=['赤蝶', '墨客'],
        team_1=['猫咪', '天星'],
        card_pool=None,
        label='Full 2v2 (all cards)',
        n_games=args.n_games,
        seed=args.seed,
    )

    # Setup 2: Stage-0-style — 1v1 mirror, no cards, bounded episode.
    profile_setup(
        team_0=['赤蝶'],
        team_1=['赤蝶'],
        card_pool=[],
        label='Stage 0 (1v1 mirror, no cards, max_rounds=3)',
        n_games=args.n_games,
        seed=args.seed,
        max_rounds=3,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
