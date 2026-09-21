"""Fixed-opponent AZ self-play."""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from gicg_env import GicgEnv
from gicg_env.env import _terminal_z
from training.core.obs_constants import OBS_META_SIZE
from training.paradigms.az.determinize import CardPoolSpec
from training.paradigms.az.mcts import MCTSConfig
import training.paradigms.az.selfplay as selfplay

SelfPlayResult = selfplay.SelfPlayResult


def play_vs_opponent_game(
    evaluator,
    env: GicgEnv,
    card_pool_spec: CardPoolSpec,
    rng: random.Random,
    mcts_config: MCTSConfig,
    opponent: Any,
    *,
    max_game_steps: int = 400,
    n_counter_slots: int,
    max_actions: int,
    agent_player: int = 0,
) -> SelfPlayResult:
    """Play one game with the MCTS agent against a fixed opponent."""
    while env.phase == 1:
        env.step(0)
        if env.done:
            game_static = evaluator.game_start(env.static_obs)
            evaluator.game_end()
            return SelfPlayResult(
                game_static=game_static,
                steps=[],
                winner=env.winner,
                n_steps=0,
                discovery_count=0,
                agent_player=agent_player,
            )

    game_static = evaluator.game_start(env.static_obs)
    steps_private: list[dict] = []
    discovery_count = 0
    profile_accum: dict[str, float] = {}

    try:
        for step_idx in range(max_game_steps):
            if env.done:
                break

            acting = env.acting_player
            if acting == agent_player:
                kinds, _ = env.get_legal_actions()
                n_legal = len(kinds)
                if n_legal == 0:
                    raise RuntimeError(
                        f'selfplay: env has 0 legal actions at step {step_idx} but is not done — engine deadlock'
                    )

                chosen, info = selfplay._mcts_decide(
                    env,
                    evaluator,
                    card_pool_spec,
                    rng,
                    mcts_config,
                    acting,
                    step_idx,
                )
                if info['discovery_events']:
                    discovery_count += 1
                if 'profile' in info:
                    for key, value in info['profile'].items():
                        if isinstance(value, (int, float)) and not key.startswith('pct_'):
                            profile_accum[key] = profile_accum.get(key, 0) + value

                steps_private.append(
                    selfplay._build_step_dict(
                        env=env,
                        mcts_info=info,
                        n_legal=n_legal,
                        n_counter_slots=n_counter_slots,
                        max_actions=max_actions,
                        acting=acting,
                    )
                )
            else:
                chosen = opponent.select_action(env)

            _, _, done, step_info = env.step(chosen)
            if step_info.get('need_target'):
                continue

            if not done and acting == agent_player:
                raw_after = env.get_dynamic_obs(perspective=acting)
                counter_start = OBS_META_SIZE
                counter_end = counter_start + n_counter_slots
                raw_block = raw_after[counter_start:counter_end].astype(np.float32)
                steps_private[-1]['counter_target'] = (raw_block - env._slot_min) / env._slot_denom
                steps_private[-1]['has_counter_target'] = True

        if env.done:
            z_p0 = _terminal_z(env.winner)
        else:
            raise RuntimeError(
                f'selfplay: game did not terminate within max_game_steps={max_game_steps}. '
                f'Either raise the cap or investigate the non-termination path.'
            )
    finally:
        evaluator.game_end()

    z_agent = z_p0 if agent_player == 0 else -z_p0
    final_steps: list[dict] = []
    for step in steps_private:
        step.pop('_acting_player')
        step['z_target'] = float(z_agent)
        final_steps.append(step)

    game_profile = {}
    if profile_accum:
        game_profile = {
            key: round(value, 6) if isinstance(value, float) else value for key, value in profile_accum.items()
        }

    return SelfPlayResult(
        game_static=game_static,
        steps=final_steps,
        winner=env.winner,
        n_steps=len(final_steps),
        discovery_count=discovery_count,
        mcts_profile=game_profile,
        agent_player=agent_player,
    )
