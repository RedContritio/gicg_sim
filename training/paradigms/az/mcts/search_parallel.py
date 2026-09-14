"""Async MCTS entry — pipelined rollouts against an inference client."""

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
from .parallel import (
    _InFlightRollout,
    _commit_parallel_rollout,
    _descend_with_vl,
)
from .rollout import _random_rollout_value
from .utils import (
    _argmax_visits,
    _detect_discovery,
    _pick_action_from_visits,
    rng_dirichlet,
)


def mcts_search_parallel(
    env,
    client,
    card_pool_spec: CardPoolSpec,
    rng: random.Random,
    viewing_player: int,
    config: MCTSConfig,
    game_step: int = 0,
) -> tuple[int, dict]:
    """Async variant of ``mcts_search`` that keeps
    ``config.parallel_rollouts`` rollouts in flight against a remote
    inference client."""
    if config.n_rollouts <= 0:
        raise ValueError(f'mcts_search_parallel: n_rollouts must be positive, got {config.n_rollouts}')
    if config.parallel_rollouts <= 0:
        raise ValueError(f'mcts_search_parallel: parallel_rollouts must be positive, got {config.parallel_rollouts}')
    if env.done:
        raise RuntimeError('mcts_search_parallel called on a terminal state')
    if env.acting_player != viewing_player:
        raise ValueError(
            f'mcts_search_parallel: viewing_player={viewing_player} '
            f'does not match env.acting_player={env.acting_player}.'
        )

    root_snap = env.snapshot()
    try:
        root = MCTSNode(turn=env.acting_player, terminal=False)
        legal_ids_root = legal_ids_from_env(env)
        if not legal_ids_root:
            raise RuntimeError('mcts_search_parallel: root has 0 legal actions')
        refs_root = env.get_action_refs()
        pay_root = env.get_legal_action_payments()
        dyn_root = env._get_obs()
        client.send_eval(dyn_root, refs_root, pay_root)
        prior_root, value_root = client.recv_eval()
        v_p0_root = value_root if root.turn == 0 else -value_root
        root.leaf_value_p0 = v_p0_root
        for i, aid in enumerate(legal_ids_root):
            root.children[aid] = MCTSNode(
                turn=-1,
                terminal=False,
                prior=float(prior_root[i]),
            )
        root.expanded = True

        n_legal_root = len(legal_ids_root)
        if config.dirichlet_eps > 0 and n_legal_root > 0:
            noise = rng_dirichlet(rng, config.dirichlet_alpha, n_legal_root)
            for i, aid in enumerate(sorted(legal_ids_root)):
                child = root.children[aid]
                child.prior = (1.0 - config.dirichlet_eps) * child.prior + config.dirichlet_eps * float(noise[i])

        opponent = 1 - viewing_player
        opp_dice_total = env.dice_total(opponent)
        n_in_flight_cap = max(1, int(config.parallel_rollouts))

        do_profile = config.profile
        prof = MCTSProfile() if do_profile else None
        _pc = _time.perf_counter

        pending: list[_InFlightRollout] = []
        rollouts_started = 0
        rollouts_done = 0
        visit_checkpoints: dict[int, ActionId] = {}

        def _start_one() -> None:
            nonlocal rollouts_started, rollouts_done

            if do_profile:
                t0 = _pc()
            env.restore(root_snap)
            env.set_simulation_seed(rng.getrandbits(63))
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
                t0 = _pc()
            in_flight, eval_inputs = _descend_with_vl(root, env, config)
            if do_profile:
                prof.descend_s += _pc() - t0
            rollouts_started += 1
            if eval_inputs is None:
                if do_profile:
                    t0 = _pc()
                _commit_parallel_rollout(in_flight, prior=None, value=None, config=config)
                if do_profile:
                    prof.n_commit += 1
                    prof.commit_s += _pc() - t0
                rollouts_done += 1
                if rollouts_done in config.discovery_checkpoints:
                    visit_checkpoints[rollouts_done] = _argmax_visits(root)
            else:
                dyn, refs, payments = eval_inputs
                if config.value_mix_lambda < 1.0:
                    if do_profile:
                        t0 = _pc()
                    in_flight.rollout_v_p0, r_steps = _random_rollout_value(
                        env,
                        config.max_rollout_depth,
                        rng,
                    )
                    if do_profile:
                        prof.n_rollout += 1
                        prof.n_rollout_steps += r_steps
                        prof.rollout_s += _pc() - t0
                if do_profile:
                    t0 = _pc()
                client.send_eval(dyn, refs, payments)
                if do_profile:
                    prof.n_eval += 1
                    prof.eval_send_s += _pc() - t0
                pending.append(in_flight)

        def _drain_one() -> None:
            nonlocal rollouts_done
            if do_profile:
                t0 = _pc()
            prior, value = client.recv_eval()
            if do_profile:
                prof.eval_recv_s += _pc() - t0
            in_flight = pending.pop(0)
            if do_profile:
                t0 = _pc()
            _commit_parallel_rollout(in_flight, prior=prior, value=value, config=config)
            if do_profile:
                prof.n_commit += 1
                prof.commit_s += _pc() - t0
            rollouts_done += 1
            if rollouts_done in config.discovery_checkpoints:
                visit_checkpoints[rollouts_done] = _argmax_visits(root)

        while rollouts_done < config.n_rollouts:
            while len(pending) < n_in_flight_cap and rollouts_started < config.n_rollouts:
                _start_one()
            if pending:
                _drain_one()

        if pending:
            raise RuntimeError(
                f'mcts_search_parallel exited with {len(pending)} in-flight rollouts — commit accounting bug'
            )

        env.restore(root_snap)
        legal_ids_final = legal_ids_from_env(env)
        n_legal = len(legal_ids_final)
        if legal_ids_final != legal_ids_root:
            raise RuntimeError(
                'mcts_search_parallel: restored root legal_ids differ from '
                'initial legal_ids — snapshot/restore invariance broken'
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
            prof.n_rollouts = rollouts_done
            info['profile'] = prof.as_dict()
        return chosen, info
    finally:
        env.snapshot_free(root_snap)
