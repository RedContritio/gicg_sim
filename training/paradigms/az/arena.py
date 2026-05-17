"""AZ arena: challenger-vs-champion binary eval."""

from __future__ import annotations

import random
import time as _time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from gicg_env import GicgEnv


@dataclass
class ArenaResult:
    """What arena_match returns."""

    challenger_wins: int
    champion_wins: int
    draws: int
    n_games: int
    wall_s: float = 0.0
    per_game_s: list = field(default_factory=list)

    @property
    def challenger_win_rate(self) -> float:
        decisive = self.n_games - self.draws
        if decisive == 0:
            return 0.5
        return self.challenger_wins / decisive


def arena_match(
    challenger,
    champion,
    env_factory: Callable[[int], GicgEnv],
    n_games: int,
    *,
    max_game_steps: int = 400,
    seed: int = 0,
    mcts_config=None,
    card_pool_spec=None,
) -> ArenaResult:
    """Play ``n_games`` full games between challenger and champion,
    alternating which side the challenger plays."""
    if n_games <= 0:
        raise ValueError(f'n_games must be positive, got {n_games}')

    rng = random.Random(seed)
    challenger_wins = 0
    champion_wins = 0
    draws = 0
    per_game_s = []

    t0_total = _time.perf_counter()
    for g in range(n_games):
        t0_game = _time.perf_counter()
        challenger_side = g % 2
        env = env_factory(g)
        winner = _play_one(
            env=env,
            p0_agent=challenger if challenger_side == 0 else champion,
            p1_agent=champion if challenger_side == 0 else challenger,
            max_game_steps=max_game_steps,
            rng=rng,
            mcts_config=mcts_config,
            card_pool_spec=card_pool_spec,
        )
        per_game_s.append(round(_time.perf_counter() - t0_game, 3))
        if winner == challenger_side:
            challenger_wins += 1
        elif winner == (1 - challenger_side):
            champion_wins += 1
        else:
            draws += 1
        env.close()

    return ArenaResult(
        challenger_wins=challenger_wins,
        champion_wins=champion_wins,
        draws=draws,
        n_games=n_games,
        wall_s=round(_time.perf_counter() - t0_total, 3),
        per_game_s=per_game_s,
    )


def _play_one(
    *,
    env: GicgEnv,
    p0_agent,
    p1_agent,
    max_game_steps: int,
    rng: random.Random,
    mcts_config=None,
    card_pool_spec=None,
) -> int:
    """Play one game. Returns the engine winner code."""
    use_mcts = mcts_config is not None and card_pool_spec is not None

    p0_agent.game_start(env.static_obs)
    p1_agent.game_start(env.static_obs)
    try:
        while env._engine.phase == 1:  # PHASE_SELECT_ACTIVE
            env.step(0)
            if env.done:
                return env._engine.winner

        for step_idx in range(max_game_steps):
            if env.done:
                return env._engine.winner

            acting = env.acting_player
            agent = p0_agent if acting == 0 else p1_agent

            kinds, _ = env.get_legal_actions()
            n_legal = len(kinds)
            if n_legal == 0:
                raise RuntimeError('arena: env has 0 legal actions on a non-terminal state')

            if use_mcts:
                from training.paradigms.az.mcts import mcts_search

                action_idx, _info = mcts_search(
                    env,
                    agent,
                    card_pool_spec,
                    rng,
                    viewing_player=acting,
                    config=mcts_config,
                    game_step=step_idx,
                )
            else:
                refs = env.get_action_refs()
                payments = env.get_legal_action_payments()
                dyn_obs = env._get_obs()
                prior, _value = agent.eval_state(dyn_obs, refs, payments)
                action_idx = int(np.argmax(prior))

            _, _, done, step_info = env.step(action_idx)
            if step_info.get('need_target'):
                raise RuntimeError('arena: legacy PendingCardTarget path hit — unsupported')

        if not env.done:
            raise RuntimeError(f'arena: game did not terminate within max_game_steps={max_game_steps}')
        return env._engine.winner
    finally:
        p0_agent.game_end()
        p1_agent.game_end()
