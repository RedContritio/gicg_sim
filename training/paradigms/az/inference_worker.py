"""Worker-process loop for the AZ parallel inference pool.

Split out of ``inference_pool.py`` so each file stays below the 300-line
cap. The main-process ``ParallelInferencePool`` class lives in
``inference_pool.py``.
"""

from __future__ import annotations

import multiprocessing as mp
import queue as queue_mod
import random as _random
import time
import traceback
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from training.paradigms.az.config import AZConfig


def worker_loop(
    worker_id: int,
    cfg: 'AZConfig',
    server_pipe,
    cmd_queue: 'mp.Queue',
    result_queue: 'mp.Queue',
    heartbeat_ts,
) -> None:
    """Child process entry for a self-play worker."""
    try:
        import threading as _threading

        import torch as _torch

        from gicg_env import GicgEnv
        from training.paradigms.az.mcts import compute_annealed_lambda
        from training.paradigms.az.pool_spec import make_pool_spec, resolve_pool_refs
        from training.paradigms.az.selfplay import play_self_game
        from training.core.inference.client import InferenceClient

        _torch.manual_seed(cfg.seed + worker_id * 1_000_000)
        rng = _random.Random(cfg.seed + worker_id * 1_000_000)
        client = InferenceClient(worker_id=worker_id, pipe=server_pipe)

        pool_by_player: Optional[dict[int, list[int]]] = None

        heartbeat_ts[worker_id] = time.time()

        def _heartbeat_loop() -> None:
            while True:
                try:
                    heartbeat_ts[worker_id] = time.time()
                except Exception:
                    return
                time.sleep(2.0)

        _threading.Thread(
            target=_heartbeat_loop,
            name=f'worker-{worker_id}-heartbeat',
            daemon=True,
        ).start()

        import os as _os

        _WORKER_HEARTBEAT_S = 30.0

        while True:
            try:
                cmd = cmd_queue.get(timeout=_WORKER_HEARTBEAT_S)
            except queue_mod.Empty:
                if _os.getppid() == 1:
                    return
                continue

            kind = cmd['kind']

            if kind == 'stop':
                return

            if kind != 'play':
                raise RuntimeError(f'worker got unknown cmd kind: {kind!r}')

            game_idx = int(cmd['game_idx'])
            env_seed = int(cmd['env_seed'])

            if pool_by_player is None:
                pool_by_player = resolve_pool_refs(cfg.scenario)
            spec = make_pool_spec(cfg.scenario, pool_by_player)

            if cfg.mcts.lambda_anneal_games > 0:
                lam = compute_annealed_lambda(cfg.mcts, game_idx)
                cfg.mcts.value_mix_lambda = lam
                cfg.mcts.prior_mix_lambda = lam
            effective_lambda = cfg.mcts.value_mix_lambda

            sample_rng = _random.Random(
                cfg.seed + worker_id * 1_000_000 + game_idx,
            )
            ep_team_0, ep_team_1 = cfg.scenario.sample_teams(sample_rng)

            env = GicgEnv(
                ep_team_0,
                ep_team_1,
                card_pool=cfg.scenario.card_pool,
                seed=env_seed,
                data_dir=cfg.scenario.data_dir,
                obs_config=cfg.obs.to_engine_json(),
                max_rounds=cfg.scenario.max_rounds,
                fix_dice=cfg.scenario.fix_dice,
                obs_mask=cfg.scenario.obs_mask,
                deck_padding=cfg.scenario.deck_padding,
                pool=cfg.scenario.pool,
            )
            env.reset(seed=env_seed)
            t0 = time.perf_counter()
            try:
                sp = play_self_game(
                    client,
                    env,
                    spec,
                    rng,
                    mcts_config=cfg.mcts,
                    max_game_steps=cfg.max_game_steps,
                    n_counter_slots=cfg.agent.n_counter_slots,
                    max_actions=cfg.agent.max_actions,
                )
            finally:
                env.close()
            wall_s = time.perf_counter() - t0

            result_queue.put(
                {
                    'worker_id': worker_id,
                    'game_idx': game_idx,
                    'game_static': sp.game_static,
                    'steps': sp.steps,
                    'winner': sp.winner,
                    'n_steps': sp.n_steps,
                    'discovery_count': sp.discovery_count,
                    'wall_s': round(wall_s, 3),
                    'effective_lambda': round(effective_lambda, 6),
                    'weight_version_at_start': client.current_weight_version,
                    'mcts_profile': sp.mcts_profile,
                    'team_0': list(ep_team_0),
                    'team_1': list(ep_team_1),
                }
            )

    except Exception as exc:
        result_queue.put(
            {
                'worker_id': worker_id,
                'error': f'{type(exc).__name__}: {exc}',
                'traceback': traceback.format_exc(),
            }
        )
