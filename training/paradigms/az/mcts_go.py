"""Go-backed MCTS search. Thin Python wrapper around the libgicg
MCTSSearch C export — produces the same return shape as
training.paradigms.az.mcts.search.mcts_search.

ctypes bindings live in ``mcts_go_bindings.py``.
"""

from __future__ import annotations

import ctypes
import json
import random
from typing import Any

import numpy as np

from training.paradigms.az.determinize import (
    CardPoolSpec,
    HiddenState,
    sample_hidden_state,
)
from training.paradigms.az.mcts import (
    ActionId,  # noqa: F401 — kept for downstream import compat
    MCTSNode,
    _detect_discovery,
    _eval_leaf,
    _pick_action_from_visits,
    legal_ids_from_env,
    rng_dirichlet,
)
from training.paradigms.az.mcts.config import MCTSConfig
from training.paradigms.az.mcts_go_bindings import ensure_lib, make_eval_callbacks


def mcts_search_go(
    env,
    evaluator,
    card_pool_spec: CardPoolSpec,
    rng: random.Random,
    viewing_player: int,
    config: MCTSConfig,
    game_step: int = 0,
) -> tuple[int, dict]:
    """Drop-in replacement for mcts_search using the Go-backed tree search."""
    if config.n_rollouts <= 0:
        raise ValueError(f'mcts_search_go: n_rollouts must be positive, got {config.n_rollouts}')
    if env.done:
        raise RuntimeError('mcts_search_go called on a terminal state')
    if env.acting_player != viewing_player:
        raise ValueError(
            f'mcts_search_go: viewing_player={viewing_player} does not match env.acting_player={env.acting_player}'
        )

    lib = ensure_lib()

    root_snap = env.snapshot()
    try:
        root = MCTSNode(turn=env.acting_player, terminal=False)
        legal_ids_root = legal_ids_from_env(env)
        _eval_leaf(root, env, evaluator, legal_ids_root)

        if config.dirichlet_eps > 0 and len(legal_ids_root) > 0:
            noise = rng_dirichlet(rng, config.dirichlet_alpha, len(legal_ids_root))
            for i, aid in enumerate(sorted(legal_ids_root)):
                child = root.children[aid]
                child.prior = (1.0 - config.dirichlet_eps) * child.prior + config.dirichlet_eps * float(noise[i])

        root_prior = np.zeros(len(legal_ids_root), dtype=np.float32)
        root_actions = np.zeros((len(legal_ids_root), 13), dtype=np.int32)
        for i, aid in enumerate(legal_ids_root):
            root_prior[i] = float(root.children[aid].prior)
            root_actions[i, 0] = int(aid[0])
            root_actions[i, 1] = int(aid[1])
            root_actions[i, 2] = int(aid[2])
            root_actions[i, 3] = int(aid[3])
            root_actions[i, 4] = int(aid[4])
            for c in range(8):
                root_actions[i, 5 + c] = int(aid[5][c])

        root_value_p0 = float(root.leaf_value_p0)

        opponent = 1 - viewing_player
        opp_dice_total = env._engine.dice_total(opponent)
        dets = []
        for _ in range(config.n_rollouts):
            hidden = sample_hidden_state(
                env,
                viewing_player,
                card_pool_spec,
                rng,
                opponent_dice_total=opp_dice_total,
            )
            dets.append(_hidden_to_json(hidden, opponent))

        worker_id = getattr(evaluator, 'worker_id', 0)
        game_id = getattr(evaluator, '_current_game_id', 0)
        seed = rng.getrandbits(64)

        input_dict = {
            'config': _config_to_dict(config),
            'root_prior': root_prior.tolist(),
            'root_value': root_value_p0,
            'root_actions': root_actions.tolist(),
            'determinizations': dets,
            'worker_id': int(worker_id),
            'game_id': int(game_id),
            'seed': int(seed),
        }
        input_json = json.dumps(input_dict).encode('utf-8')

        n_root = len(legal_ids_root)
        visits_buf = (ctypes.c_int * n_root)()
        root_value_out = ctypes.c_float(0.0)
        profile_json_out = ctypes.c_char_p(None)

        send_cb, recv_cb = make_eval_callbacks(evaluator)

        env.restore(root_snap)

        rc = lib.MCTSSearch(
            env._engine._handle,
            root_snap,
            input_json,
            send_cb,
            recv_cb,
            visits_buf,
            ctypes.c_int(n_root),
            ctypes.byref(root_value_out),
            ctypes.byref(profile_json_out),
        )
        if rc != 0:
            raise RuntimeError(f'MCTSSearch failed with code {rc}')

        visits_np = np.array(visits_buf, dtype=np.int32)

        env.restore(root_snap)
        legal_ids_final = legal_ids_from_env(env)
        if legal_ids_final != legal_ids_root:
            raise RuntimeError(
                'mcts_search_go: restored root legal_ids differ from initial — snapshot/restore invariance broken'
            )

        visits = {aid: int(visits_np[i]) for i, aid in enumerate(legal_ids_final)}
        visit_arr = visits_np.astype(np.float32)
        chosen, pi = _pick_action_from_visits(
            visit_arr,
            len(legal_ids_final),
            config,
            game_step,
            rng,
        )
        discovery_events = _detect_discovery({}, config.discovery_checkpoints)

        info: dict[str, Any] = {
            'visits': visits,
            'pi': pi,
            'legal_ids': legal_ids_final,
            'discovery_events': discovery_events,
            'root_value_p0': float(root_value_out.value),
            'visit_checkpoints': {},
        }
        if profile_json_out.value is not None:
            info['profile'] = json.loads(profile_json_out.value.decode('utf-8'))
            ctypes.CDLL(None).free(profile_json_out)
        return chosen, info
    finally:
        env.snapshot_free(root_snap)


def _hidden_to_json(hidden: HiddenState, opponent: int) -> dict:
    d = {
        'opponent': int(opponent),
        'hand': [int(x) for x in hidden.opponent_hand],
        'deck': [int(x) for x in hidden.opponent_deck],
    }
    if hidden.opponent_dice_colors is not None:
        d['dice'] = [int(x) for x in hidden.opponent_dice_colors]
    else:
        d['dice'] = None
    return d


def _config_to_dict(c: MCTSConfig) -> dict:
    return {
        'n_rollouts': int(c.n_rollouts),
        'c_puct': float(c.c_puct),
        'dirichlet_alpha': float(c.dirichlet_alpha),
        'dirichlet_eps': float(c.dirichlet_eps),
        'temperature': float(c.temperature),
        'temperature_switch_step': int(c.temperature_switch_step),
        'max_rollout_depth': int(c.max_rollout_depth),
        'parallel_rollouts': int(getattr(c, 'parallel_rollouts', 1)),
        'value_mix_lambda': float(c.value_mix_lambda),
        'prior_mix_lambda': float(c.prior_mix_lambda),
        'lambda_anneal_games': 0,
        'lambda_start': 0.0,
        'lambda_end': 0.0,
        'game_idx': 0,
        'profile': bool(c.profile),
        'virtual_loss': int(getattr(c, 'virtual_loss', 1)),
    }
