"""AZ self-play — one function that plays one full game and returns
a (game_static, steps) pair ready to hand to ReplayBuffer."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
import numpy as np
from training.core.step_encoding import parse_buffs_np

from gicg_env import GicgEnv
from gicg_env.env import _terminal_z
from training.paradigms.az.determinize import CardPoolSpec
from training.paradigms.az.mcts import MCTSConfig, mcts_search, mcts_search_parallel
from training.core.inference.client import InferenceClient
from training.core.obs_constants import OBS_META_SIZE
from training.core.step_encoding import (
    build_legal_mask,
    pad_action_payments,
    pad_action_refs,
    parse_dynamic_np,
    parse_dynamic_typed_np,
)


@dataclass
class SelfPlayResult:
    """Everything play_self_game returns."""

    game_static: dict
    steps: list[dict]
    winner: int
    n_steps: int
    discovery_count: int
    mcts_profile: dict = field(default_factory=dict)
    agent_player: int | None = None


def _mcts_decide(
    env: GicgEnv,
    evaluator,
    card_pool_spec: CardPoolSpec,
    rng: random.Random,
    mcts_config: MCTSConfig,
    acting: int,
    game_step: int,
):
    """Run one MCTS decision for ``acting`` — shared dispatch across the
    mirror (``play_self_game``) and fixed-opponent
    (``play_vs_opponent_game``) paths. Backend selection order is
    load-bearing history; do not reorder."""
    if mcts_config.backend == 'go':
        from training.paradigms.az.mcts_go import mcts_search_go

        return mcts_search_go(
            env,
            evaluator,
            card_pool_spec,
            rng,
            viewing_player=acting,
            config=mcts_config,
            game_step=game_step,
        )
    if mcts_config.parallel_rollouts > 1 and isinstance(evaluator, InferenceClient):
        return mcts_search_parallel(
            env,
            evaluator,
            card_pool_spec,
            rng,
            viewing_player=acting,
            config=mcts_config,
            game_step=game_step,
        )
    return mcts_search(
        env,
        evaluator,
        card_pool_spec,
        rng,
        viewing_player=acting,
        config=mcts_config,
        game_step=game_step,
    )


def play_self_game(
    evaluator,
    env: GicgEnv,
    card_pool_spec: CardPoolSpec,
    rng: random.Random,
    mcts_config: MCTSConfig,
    *,
    max_game_steps: int = 400,
    n_counter_slots: int,
    max_actions: int,
) -> SelfPlayResult:
    """Play one full self-play game on ``env`` with ``evaluator``,
    driving every decision through MCTS."""
    while env.phase == 1:  # PHASE_SELECT_ACTIVE
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
            )

    game_static = evaluator.game_start(env.static_obs)

    steps_private: list[dict] = []
    discovery_count = 0
    _profile_accum: dict[str, float] = {}

    try:
        for step_idx in range(max_game_steps):
            if env.done:
                break

            acting = env.acting_player
            kinds, _ = env.get_legal_actions()
            n_legal = len(kinds)
            if n_legal == 0:
                raise RuntimeError(
                    f'selfplay: env has 0 legal actions at step {step_idx} but is not done — engine deadlock'
                )

            chosen, info = _mcts_decide(
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
                for k, v in info['profile'].items():
                    if isinstance(v, (int, float)) and not k.startswith('pct_'):
                        _profile_accum[k] = _profile_accum.get(k, 0) + v

            step = _build_step_dict(
                env=env,
                mcts_info=info,
                n_legal=n_legal,
                n_counter_slots=n_counter_slots,
                max_actions=max_actions,
                acting=acting,
            )
            steps_private.append(step)

            _, _, done, step_info = env.step(chosen)
            if step_info.get('need_target'):
                # Normal mid-game state, not an error (gicg_env/env.py
                # step docstring): the played action left a pending
                # target / forced-switch continuation, and the NEXT
                # iteration's acting player resolves it from the new
                # legal list (env.step routes to the target resolver
                # automatically). The semantic pipelines
                # (tools/experiments/semantic_training/rl_rollout.py,
                # evaluate.py) never special-case it — same behavior
                # here. The after-state is a pending-target
                # intermediate, NOT the resolved decision state, so
                # this step keeps has_counter_target=False.
                continue

            if not done:
                raw_after = env.get_dynamic_obs(perspective=acting)
                c_start = OBS_META_SIZE
                c_end = c_start + n_counter_slots
                raw_block = raw_after[c_start:c_end].astype(np.float32)
                normalized = (raw_block - env._slot_min) / env._slot_denom
                steps_private[-1]['counter_target'] = normalized
                steps_private[-1]['has_counter_target'] = True

        if env.done:
            winner = env.winner
            z_p0 = _terminal_z(winner)
        else:
            raise RuntimeError(
                f'selfplay: game did not terminate within '
                f'max_game_steps={max_game_steps}. Either raise the cap '
                f'or investigate the non-termination path.'
            )
    finally:
        evaluator.game_end()

    final_steps: list[dict] = []
    for step in steps_private:
        acting = step.pop('_acting_player')
        z_view = z_p0 if acting == 0 else -z_p0
        step['z_target'] = float(z_view)
        final_steps.append(step)

    game_profile = {}
    if _profile_accum:
        game_profile = {k: round(v, 6) if isinstance(v, float) else v for k, v in _profile_accum.items()}

    return SelfPlayResult(
        game_static=game_static,
        steps=final_steps,
        winner=env.winner,
        n_steps=len(final_steps),
        discovery_count=discovery_count,
        mcts_profile=game_profile,
    )


def _build_step_dict(
    *,
    env: GicgEnv,
    mcts_info: dict,
    n_legal: int,
    n_counter_slots: int,
    max_actions: int,
    acting: int,
) -> dict:
    """Assemble one per-step dict for the replay buffer."""
    dyn_obs = env._get_obs()
    counter_values, meta, card_buckets, enemy_sizes = parse_dynamic_np(
        dyn_obs,
        n_counter_slots,
        copy=True,
    )
    recent_damage, prepare_skill, modifier_log = parse_dynamic_typed_np(
        dyn_obs,
        n_counter_slots,
        copy=True,
        include_modifier_log=True,
    )

    refs_raw = env.get_action_refs()
    payments_raw = env.get_legal_action_payments()
    padded_refs = pad_action_refs(refs_raw, max_actions)
    padded_payments = pad_action_payments(payments_raw, max_actions)

    legal_mask = build_legal_mask(max_actions, n_legal)

    pi_flat = np.zeros(max_actions, dtype=np.float32)
    pi_flat[:n_legal] = mcts_info['pi']

    is_discovery = bool(mcts_info['discovery_events'])

    return {
        'counter_values': counter_values,
        'meta': meta,
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'recent_damage': recent_damage,
        'prepare_skill': prepare_skill,
        'modifier_log': modifier_log,
        'buffs': parse_buffs_np(dyn_obs, n_counter_slots),
        'action_refs': padded_refs.astype(np.int64),
        'action_payments': padded_payments.astype(np.float32),
        'legal_mask': legal_mask,
        'pi_target': pi_flat,
        'is_discovery': is_discovery,
        'counter_target': np.zeros(n_counter_slots, dtype=np.float32),
        'has_counter_target': False,
        '_acting_player': acting,
    }


from training.paradigms.az.selfplay_fixed import play_vs_opponent_game  # noqa: E402,F401
