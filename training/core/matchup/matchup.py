"""Matchup runner: symmetric two-player evaluation with optional team
enumeration.

Player-spec → builder dispatch lives in ``.loaders`` so this file stays
below the 300-line cap.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from itertools import combinations
from typing import List, Tuple

from gicg_env import GicgEnv
from training.core.matchup.loaders import PlayerBuilder, load_player


def enumerate_disjoint_teams(
    char_pool: List[str],
    team_size: int,
) -> List[Tuple[List[str], List[str]]]:
    """Enumerate all unordered disjoint (team_0, team_1) pairs from
    ``char_pool``.

    For 5-char pool + team_size=2: 5 choose 2 = 10 team_0 options ×
    3 choose 2 = 3 team_1 options from remaining, folded by
    unordered-pair symmetry = 15 matchups. Caller multiplies by 2
    for side-swap → 30 game configurations.
    """
    if team_size * 2 > len(char_pool):
        raise ValueError(f'enumerate_disjoint: team_size={team_size} × 2 > pool size {len(char_pool)}')
    if team_size <= 0:
        raise ValueError(f'team_size must be positive, got {team_size}')

    seen: set = set()
    pairs: List[Tuple[List[str], List[str]]] = []
    for team_0 in combinations(char_pool, team_size):
        remaining = [c for c in char_pool if c not in team_0]
        for team_1 in combinations(remaining, team_size):
            key = frozenset([frozenset(team_0), frozenset(team_1)])
            if key in seen:
                continue
            seen.add(key)
            pairs.append((list(team_0), list(team_1)))
    return pairs


def _play_one(
    env: GicgEnv,
    p0_player,
    p1_player,
    max_game_steps: int,
) -> int:
    """Play one game. Returns engine winner code (0, 1, or -1 for draw)."""
    while env.phase == 1:  # PHASE_SELECT_ACTIVE
        env.step(0)
        if env.done:
            return env.winner

    for _ in range(max_game_steps):
        if env.done:
            return env.winner
        acting = env.acting_player
        player = p0_player if acting == 0 else p1_player
        action_idx = player.select_action(env)
        _, _, done, step_info = env.step(action_idx)
        if step_info.get('need_target'):
            raise RuntimeError('matchup: legacy PendingCardTarget path hit — unsupported')
    if not env.done:
        raise RuntimeError(f'matchup: game did not terminate within max_game_steps={max_game_steps}')
    return env.winner


@dataclass
class CellStats:
    wins: int = 0  # players[0] wins (side-swap adjusted)
    losses: int = 0
    draws: int = 0
    wall_s: float = 0.0

    @property
    def n_games(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_rate(self) -> float:
        decisive = self.n_games - self.draws
        if decisive == 0:
            return 0.5
        return self.wins / decisive

    def to_dict(self) -> dict:
        return {
            'wins': self.wins,
            'losses': self.losses,
            'draws': self.draws,
            'n_games': self.n_games,
            'win_rate': round(self.win_rate, 4),
            'wall_s': round(self.wall_s, 2),
        }


def _play_cell(
    builder_0: PlayerBuilder,
    builder_1: PlayerBuilder,
    team_0: List[str],
    team_1: List[str],
    games_per_cell: int,
    max_game_steps: int,
    base_seed: int,
    data_dir: str | None,
    card_pool: List[str] | None,
    deck_padding: dict | None = None,
    pool: object | None = None,
    swap_sides: bool = True,
) -> CellStats:
    """Play games and tally win/loss/draw from players[0]'s perspective."""
    stats = CellStats()
    t0 = time.perf_counter()

    # swap_sides=True: env teams stay fixed (env-side-0=team_0, env-side-1=team_1),
    # but primary alternates which env-side it plays. So with asymmetric teams,
    # primary plays each character in 50/50 of games — fair head-to-head.
    # Old behavior was "swap first/second mover" only (primary always played team_0
    # char), which under-counted asymmetry biases. Mirror match (team_0==team_1)
    # gives identical results either way.
    n_games = (2 * games_per_cell) if swap_sides else games_per_cell
    for g in range(n_games):
        primary_plays_team_1 = swap_sides and (g % 2 == 1)
        seed = base_seed + g

        env = GicgEnv(
            team_0,
            team_1,
            card_pool=card_pool,
            seed=seed,
            data_dir=data_dir,
            deck_padding=deck_padding,
            pool=pool,
        )
        env.reset(seed=seed)
        try:
            p_primary = builder_0(seed)
            p_secondary = builder_1(seed + 10_000)
            if not primary_plays_team_1:
                # primary plays env-side-0 (team_0 character)
                winner = _play_one(env, p_primary, p_secondary, max_game_steps)
                primary_side = 0
            else:
                # primary plays env-side-1 (team_1 character)
                winner = _play_one(env, p_secondary, p_primary, max_game_steps)
                primary_side = 1

            if winner == primary_side:
                stats.wins += 1
            elif winner == (1 - primary_side):
                stats.losses += 1
            else:
                stats.draws += 1
        finally:
            env.close()

    stats.wall_s = time.perf_counter() - t0
    return stats


@dataclass
class MatchupResult:
    players: List[dict]
    aggregate: CellStats = field(default_factory=CellStats)
    per_cell: List[dict] = field(default_factory=list)
    wall_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            'players': self.players,
            'wall_s': round(self.wall_s, 2),
            'aggregate': self.aggregate.to_dict(),
            'per_cell': self.per_cell,
        }


def run_matchup(
    players: List[dict],
    *,
    mode: str,
    team_0: List[str] | None = None,
    team_1: List[str] | None = None,
    char_pool: List[str] | None = None,
    team_size: int | None = None,
    card_pool: List[str] | None = None,
    games_per_cell: int = 10,
    max_game_steps: int = 400,
    seed: int = 0,
    data_dir: str | None = None,
    deck_padding: dict | None = None,
    pool: object | None = None,
    swap_sides: bool = True,
) -> MatchupResult:
    """Run one matchup: two players, over one or many team pairs."""
    if len(players) != 2:
        raise ValueError(f'run_matchup: expected 2 players, got {len(players)}')
    if games_per_cell <= 0:
        raise ValueError(f'games_per_cell must be positive, got {games_per_cell}')

    if mode == 'fixed':
        if team_0 is None or team_1 is None:
            raise ValueError('run_matchup mode=fixed requires team_0 and team_1')
        team_pairs = [(list(team_0), list(team_1))]
    elif mode == 'enumerate_disjoint':
        if char_pool is None or team_size is None:
            raise ValueError('run_matchup mode=enumerate_disjoint requires char_pool and team_size')
        team_pairs = enumerate_disjoint_teams(char_pool, team_size)
    else:
        raise ValueError(f'unknown mode: {mode!r}')

    builder_0 = load_player(players[0])
    builder_1 = load_player(players[1])

    result = MatchupResult(players=players)
    agg = CellStats()

    t0_total = time.perf_counter()
    for ti, (tt0, tt1) in enumerate(team_pairs):
        cell_seed = seed + ti * 10_000
        cs = _play_cell(
            builder_0,
            builder_1,
            tt0,
            tt1,
            games_per_cell,
            max_game_steps,
            cell_seed,
            data_dir,
            card_pool,
            deck_padding=deck_padding,
            pool=pool,
            swap_sides=swap_sides,
        )
        result.per_cell.append(
            {
                'team_0': tt0,
                'team_1': tt1,
                **cs.to_dict(),
            }
        )
        agg.wins += cs.wins
        agg.losses += cs.losses
        agg.draws += cs.draws
        agg.wall_s += cs.wall_s

    result.aggregate = agg
    result.wall_s = time.perf_counter() - t0_total
    return result
