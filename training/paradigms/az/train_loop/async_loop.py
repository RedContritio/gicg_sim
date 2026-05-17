"""Async AZ training loop — coordinates inference server, worker pool,
replay buffer ingest, train thread, arena, gauntlet dispatch.

Phase 2-ζ (FU-W4-AZ-rewrite, T2.ζ) — inlined from
``training.paradigms.az.legacy.train_loop.async_loop``. All internal
imports point at adapter top-level (``paradigms.az.buffer`` for
ReplayBuffer mv'd at T2.5, ``paradigms.az.network`` for Agent inlined
at T2.6, ``paradigms.az.train_step`` inlined at T2.ζ alongside this
file). STRICT T2.11 zero-legacy verified by
``test_az_config_train_loop_phase2_zeta.py``.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

import torch

from training.core.env_factory import make_env_factory
from training.core.gauntlet import dispatch_gauntlet
from training.core.health_check import health_check
from training.core.system_monitor import system_monitor_loop
from training.paradigms.az.train_loop.helpers import (
    cpu_state_dict,
    ingest_trajectory,
    maybe_arena,
)
from training.paradigms.az.train_loop.run_result import RunResult
from training.paradigms.az.train_loop.stats_ingest import stats_ingest_loop


def run_async(
    config,
    artifacts_dir: Optional[Path],
    log,
) -> RunResult:
    """Async training loop — one pool of workers streams trajectories
    into a shared buffer while the main process trains + evaluates."""
    from training.paradigms.az.buffer import ReplayBuffer
    from training.paradigms.az.inference_pool import ParallelInferencePool, PoolDeadlock
    from training.paradigms.az.network import Agent
    from training.paradigms.az.train_step import train_step

    torch.manual_seed(config.seed)

    challenger = Agent(config.agent, lr=1e-3)
    if getattr(config, 'init_from_ckpt', None):
        ckpt_path = config.init_from_ckpt
        blob = torch.load(ckpt_path, map_location='cpu', weights_only=True)
        # bc_train + Agent.save format: {'cfg': dict, 'net': state_dict}.
        # Plain state_dict (legacy) also accepted.
        state = blob['net'] if isinstance(blob, dict) and 'net' in blob else blob
        challenger.net.load_state_dict(state)
        print(f'[init_from_ckpt] loaded BC pretrain from {ckpt_path}')
    champion = Agent(config.agent)
    champion.net.load_state_dict(challenger.net.state_dict())

    buffer = ReplayBuffer(
        capacity=config.buffer_capacity,
        priority_weight=config.priority_weight,
    )

    rng = random.Random(config.seed)
    env_factory = make_env_factory(config, config.obs.to_engine_json(), master_seed=config.seed)
    result = RunResult(
        n_games_played=0,
        artifacts_dir=str(artifacts_dir) if artifacts_dir else None,
    )

    pool = ParallelInferencePool(config)
    pool.start()
    main_weight_version = 1
    pool.push_weights(cpu_state_dict(challenger))

    state_lock = threading.Lock()
    stop_flag = threading.Event()
    last_arena_game = 0
    last_gauntlet_game = 0
    last_ckpt_game = [0]
    v_loss_window: deque = deque(maxlen=50)
    weight_version_ref = [main_weight_version]

    for game_idx in range(config.n_games):
        pool.dispatch(game_idx=game_idx, env_seed=config.seed + game_idx)

    ingest_error: dict = {}

    def _ingest_loop() -> None:
        try:
            consumed = 0
            while consumed < config.n_games:
                try:
                    res = pool.next_result(timeout=None)
                except PoolDeadlock as exc:
                    log(
                        'ingest_abort',
                        {
                            'consumed': consumed,
                            'dispatched': pool.dispatched_count(),
                            'alive_workers': pool.alive_workers(),
                            'reason': str(exc),
                        },
                    )
                    break
                with state_lock:
                    ingest_trajectory(
                        res,
                        buffer,
                        result,
                        log,
                        main_weight_version=weight_version_ref[0],
                    )
                consumed += 1
        except Exception as exc:
            ingest_error['exc'] = exc
            stop_flag.set()
        finally:
            stop_flag.set()

    ingest_thread = threading.Thread(
        target=_ingest_loop,
        name='az-ingest',
        daemon=True,
    )
    ingest_thread.start()

    stats_stop = threading.Event()
    stats_thread = threading.Thread(
        target=stats_ingest_loop,
        name='az-stats',
        args=(pool.stats_queue, log, stats_stop),
        daemon=True,
    )
    stats_thread.start()

    sys_stop = threading.Event()
    sys_thread = threading.Thread(
        target=system_monitor_loop,
        name='az-sysmon',
        args=(log, sys_stop, float(config.sysmon_interval_s)),
        daemon=True,
    )
    sys_thread.start()

    t0 = time.perf_counter()
    try:
        train_tick = 0
        while True:
            ingest_done = stop_flag.is_set() and not ingest_thread.is_alive()

            with state_lock:
                buf_size = len(buffer)
                games_so_far = result.n_games_played

            if buf_size >= config.min_buffer_before_train:
                for train_iter in range(config.train_steps_per_game):
                    with state_lock:
                        batch = buffer.sample(config.batch_size, rng)
                    stats = train_step(challenger, batch, config.train)
                    stats_with_game = {
                        'train_tick': train_tick,
                        'games_so_far': games_so_far,
                        'train_iter': train_iter,
                        **stats,
                    }
                    result.training_stats.append(stats_with_game)
                    log('train', stats_with_game)
                    health_check(stats, v_loss_window, log)
                train_tick += 1

                if train_tick % max(config.sync_weights_every_train_steps, 1) == 0:
                    main_weight_version += 1
                    weight_version_ref[0] = main_weight_version
                    pool.push_weights(cpu_state_dict(challenger))
                    log(
                        'weight_push',
                        {
                            'train_tick': train_tick,
                            'weight_version': main_weight_version,
                        },
                    )

                if train_tick % 10 == 0:
                    with state_lock:
                        log('buffer', buffer.stats())

            with state_lock:
                games_completed = result.n_games_played
            fire_arena = (
                config.games_per_arena > 0
                and games_completed - last_arena_game >= config.games_per_arena
                and games_completed > 0
            )
            if fire_arena:
                last_arena_game = games_completed - (games_completed % config.games_per_arena)
                maybe_arena(
                    config,
                    challenger,
                    champion,
                    env_factory,
                    last_arena_game,
                    result,
                    log,
                    artifacts_dir,
                )
            fire_gauntlet = (
                config.games_per_gauntlet > 0
                and games_completed - last_gauntlet_game >= config.games_per_gauntlet
                and games_completed > 0
            )
            if fire_gauntlet:
                last_gauntlet_game = games_completed - (games_completed % config.games_per_gauntlet)
                dispatch_gauntlet(
                    config,
                    challenger,
                    artifacts_dir,
                    last_gauntlet_game,
                    log,
                )

            if (
                artifacts_dir is not None
                and config.checkpoint_every_n_games > 0
                and games_completed - last_ckpt_game[0] >= config.checkpoint_every_n_games
                and games_completed > 0
            ):
                ckpt_marker = games_completed - (games_completed % config.checkpoint_every_n_games)
                last_ckpt_game[0] = ckpt_marker
                ckpt_path = str(artifacts_dir / f'ckpt_g{ckpt_marker:05d}.pt')
                challenger.save(ckpt_path)
                log('checkpoint', {'game': ckpt_marker, 'path': ckpt_path})

            if ingest_done:
                with state_lock:
                    buf_size_final = len(buffer)
                if buf_size_final < config.min_buffer_before_train:
                    break
                if train_tick > 0:
                    break

            time.sleep(0.01)
    finally:
        stats_stop.set()
        sys_stop.set()
        ingest_thread.join(timeout=30)
        stats_thread.join(timeout=2)
        sys_thread.join(timeout=2)
        pool.stop()

    if 'exc' in ingest_error:
        raise ingest_error['exc']

    if artifacts_dir is not None:
        challenger.save(str(artifacts_dir / 'final_challenger.pt'))
        champion.save(str(artifacts_dir / 'final_champion.pt'))
        log(
            'done',
            {
                'duration_s': time.perf_counter() - t0,
                'games': result.n_games_played,
            },
        )

    return result
