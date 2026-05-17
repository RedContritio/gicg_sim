"""MCTS sync + async entry points.

Split into two functions in two files: ``mcts_search`` here and
``mcts_search_parallel`` in ``search_parallel.py`` — they don't share
inner helpers beyond what's already factored out to
``rollout`` / ``run_rollout`` / ``parallel`` / ``utils``."""

from __future__ import annotations

import random
import time as _time

import numpy as np

from training.paradigms.az.determinize import (
    CardPoolSpec,
    apply_determinization,
    sample_hidden_state,
)

from .action_id import ActionId, legal_ids_from_env
from .config import MCTSConfig, MCTSProfile
from .node import MCTSNode
from .rollout import _eval_leaf
from .run_rollout import run_rollout
from .utils import (
    _argmax_visits,
    _detect_discovery,
    _pick_action_from_visits,
    rng_dirichlet,
)

# Re-export mcts_search_parallel at the package level.
from .search_parallel import mcts_search_parallel  # noqa: F401


def mcts_search(
    env,
    evaluator,
    card_pool_spec: CardPoolSpec,
    rng: random.Random,
    viewing_player: int,
    config: MCTSConfig,
    game_step: int = 0,
) -> tuple[int, dict]:
    """Run ``config.n_rollouts`` IS-UCT rollouts from env's current
    state and return ``(chosen_action_idx, info)``."""
    if config.n_rollouts <= 0:
        raise ValueError(f'mcts_search: n_rollouts must be positive, got {config.n_rollouts}')
    if env.done:
        raise RuntimeError('mcts_search called on a terminal state')
    if env.acting_player != viewing_player:
        raise ValueError(
            f'mcts_search: viewing_player={viewing_player} does not '
            f'match env.acting_player={env.acting_player}. You may '
            'only search from the perspective of the player currently '
            'owed a decision.'
        )

    do_profile = config.profile
    prof = MCTSProfile() if do_profile else None
    _pc = _time.perf_counter

    root_snap = env.snapshot()
    try:
        root = MCTSNode(turn=env.acting_player, terminal=False)
        legal_ids_root = legal_ids_from_env(env)
        _eval_leaf(root, env, evaluator, legal_ids_root)

        n_legal_root = len(legal_ids_root)
        if config.dirichlet_eps > 0 and n_legal_root > 0:
            noise = rng_dirichlet(rng, config.dirichlet_alpha, n_legal_root)
            for i, aid in enumerate(sorted(legal_ids_root)):
                child = root.children[aid]
                child.prior = (1.0 - config.dirichlet_eps) * child.prior + config.dirichlet_eps * float(noise[i])

        opponent = 1 - viewing_player
        opp_dice_total = env._engine.dice_total(opponent)

        visit_checkpoints: dict[int, ActionId] = {}
        for rollout_i in range(config.n_rollouts):
            if do_profile:
                t0 = _pc()
            env.restore(root_snap)
            if do_profile:
                prof.n_restore += 1
                prof.restore_s += _pc() - t0
                t0 = _pc()
            hidden = sample_hidden_state(
                env,
                viewing_player,
                card_pool_spec,
                rng,
                opponent_dice_total=opp_dice_total,
            )
            apply_determinization(env, hidden, opponent)
            if do_profile:
                prof.n_determinize += 1
                prof.determinize_s += _pc() - t0
            run_rollout(root, env, evaluator, config, rng, prof=prof)

            rollouts_done = rollout_i + 1
            if rollouts_done in config.discovery_checkpoints:
                visit_checkpoints[rollouts_done] = _argmax_visits(root)

        env.restore(root_snap)
        legal_ids_final = legal_ids_from_env(env)
        n_legal = len(legal_ids_final)

        if legal_ids_final != legal_ids_root:
            raise RuntimeError(
                'MCTS: restored root legal_ids differ from initial legal_ids — snapshot/restore invariance broken'
            )

        visits = {aid: root.children[aid].N for aid in legal_ids_final}
        visit_arr = np.array(
            [visits[aid] for aid in legal_ids_final],
            dtype=np.float32,
        )

        chosen, pi = _pick_action_from_visits(
            visit_arr,
            n_legal,
            config,
            game_step,
            rng,
        )

        discovery_events = _detect_discovery(
            visit_checkpoints,
            config.discovery_checkpoints,
        )

        root_q_p0 = root.W / max(root.N, 1)
        info = {
            'visits': visits,
            'pi': pi,
            'legal_ids': legal_ids_final,
            'discovery_events': discovery_events,
            'root_value_p0': root_q_p0,
            'visit_checkpoints': visit_checkpoints,
        }
        if do_profile:
            prof.n_rollouts = config.n_rollouts
            info['profile'] = prof.as_dict()
        return chosen, info
    finally:
        env.snapshot_free(root_snap)
