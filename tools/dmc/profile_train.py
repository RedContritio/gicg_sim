"""Mac CPU full-train DMC pipeline benchmark — cProfile + throughput.

Extends tools.dmc.profile_actor (collector-only) to cover the full
training loop: collect + buffer.push + train_step (forward + backward
+ optimizer.step). Uses 3-phase wall window (warmup / measure / tail)
so cProfile + throughput numbers only reflect the steady-state regime.

Usage (Mac dev — full 600s baseline):

    .venv/bin/python -m tools.dmc.profile_train --cfg configs/dmc/smoke.toml --duration-seconds 600

Usage (Windows X3D — same tool, longer runs):

    ssh dev@<windows-host> 'cd D:\\gicg_dev && .\\.venv\\Scripts\\python.exe -m tools.dmc.profile_train --cfg configs\\dmc\\smoke.toml --duration-seconds 600'

Outputs:
- ``train.prof`` (cProfile binary, MEASURE WINDOW ONLY) — view with snakeviz
- stdout: 3-phase summary + steady-state throughput + top-N hotspots

Comparison anchor: profile_actor.py (collector-only) Mac M-series
baseline 274 fps. This tool's transitions_per_s should be LOWER (train
step competes for CPU); train_steps_per_s is the new metric.

Mac data: hotspot identification + Windows X3D cross-platform delta
anchor, NOT a production target.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import time
from pathlib import Path
from typing import Any

import torch

from training.core.actor._mp_helpers import harden_child_env


def _build_full_components(cfg: Any) -> tuple[Any, Any, Any, Any, Any, Any, Any, Any]:
    """Mirror tools.runs._train.dispatch.run_paradigm_train +
    training.core.pipeline.run_pipeline construction shape — full
    training loop (collector + buffer + optimizer + loss + network).

    Returns (state, paradigm, collector, provider, buffer, optimizer,
    loss_fn, network).
    """
    from training.core.actor.network_provider import LocalNetworkProvider
    from training.core.env_factory import make_env_factory
    from training.core.protocols import PipelineState
    from training.paradigms import resolve as resolve_paradigm

    paradigm = resolve_paradigm(cfg.meta.paradigm)
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)

    network = paradigm.make_network(cfg)
    opp_pool = paradigm.make_opponent_pool(cfg, network) if hasattr(paradigm, 'make_opponent_pool') else None
    collector = paradigm.make_collector(cfg, env_factory, network, opp_pool)
    provider = LocalNetworkProvider(network, device=cfg.meta.device)

    optimizer = paradigm.make_optimizer(cfg, network)
    buffer = paradigm.make_buffer(cfg)
    loss_fn = paradigm.make_loss(cfg)

    state = PipelineState.fresh(cfg.meta.seed)
    return state, paradigm, collector, provider, buffer, optimizer, loss_fn, network


def _run_one_iter(
    state: Any,
    cfg: Any,
    paradigm: Any,
    collector: Any,
    provider: Any,
    buffer: Any,
    optimizer: Any,
    loss_fn: Any,
    network: Any,
    counters: dict,
) -> None:
    """Mirror training.core.pipeline.run_pipeline main loop body
    (lines 99-141 of pipeline.py) MINUS ckpt / eval / log / nan_guard
    branches. Only collect + train_step + state.after_* are exercised.
    """
    plan = paradigm.step_schedule(state, cfg)

    if plan.collect:
        out = collector.collect(plan.n_episodes, provider)
        buffer.push(out)
        state.after_collect(out)
        counters['n_collect_calls'] += 1
        counters['n_transitions'] += int(out.n_units or out.n_transitions)

    if plan.train and plan.n_train_batches > 0:
        for _ in range(plan.n_train_batches):
            if len(buffer) < plan.batch_size:
                break
            batch = buffer.sample(plan.batch_size)
            optimizer.zero_grad()
            loss_result = loss_fn.compute(network, batch)
            loss_result.loss.backward()
            torch.nn.utils.clip_grad_norm_(
                network.parameters(),
                cfg.paradigm.get('max_grad_norm', 1.0),
            )
            optimizer.step()
            state.after_train(loss_result.breakdown)
            counters['n_train_steps'] += 1

    if plan.clear_buffer_after_train:
        buffer.clear()

    state.advance(plan)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='DMC full-train cProfile harness (3-phase wall window: warmup / measure / tail).',
    )
    p.add_argument('--cfg', required=True, type=Path, help='Path to DMC TOML cfg.')
    p.add_argument(
        '--duration-seconds',
        type=int,
        default=600,
        help='Total wall (default 600). Must be >= warmup + tail + 30s minimum measure.',
    )
    p.add_argument(
        '--warmup-seconds',
        type=int,
        default=60,
        help='Phase 1 wall — buffer fill + JIT/import warmup; counters reset at boundary (default 60).',
    )
    p.add_argument(
        '--tail-seconds',
        type=int,
        default=60,
        help='Phase 3 wall — run out clock after measurement (default 60).',
    )
    p.add_argument(
        '--prof-output',
        type=str,
        default='train.prof',
        help='cProfile binary output (measure window only, default train.prof).',
    )
    p.add_argument(
        '--top-hotspots',
        type=int,
        default=15,
        help='How many cumulative-time rows to print (default 15).',
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    measure_seconds = args.duration_seconds - args.warmup_seconds - args.tail_seconds
    if measure_seconds < 30:
        raise SystemExit(
            f'profile_train: measure window {measure_seconds}s < 30s minimum '
            f'(duration={args.duration_seconds} warmup={args.warmup_seconds} '
            f'tail={args.tail_seconds}).',
        )

    # Mirror real actor process startup — single-actor profile should
    # not oversubscribe the box. harden_child_env is idempotent.
    harden_child_env()

    from training.core.config.loader import load_cfg

    cfg = load_cfg(args.cfg, overrides=[])
    if cfg.meta.paradigm != 'dmc':
        raise SystemExit(
            f'profile_train: cfg.meta.paradigm must be "dmc", got {cfg.meta.paradigm!r}',
        )

    # In-memory override: cfg.paradigm.total_frames caps the train loop via
    # step_schedule (paradigm.py:154). Smoke cfg ships total_frames=1000 which
    # is hit within the first few seconds of warmup, causing the measure window
    # to spin on empty step_schedule plans rather than do real work. The tool
    # writes no artifacts, so this in-memory bump never touches persistent cfg.
    if isinstance(cfg.paradigm, dict):
        cfg.paradigm['total_frames'] = 10**12
    print('[profile_train] cfg.paradigm.total_frames overridden to 1e12 (benchmark mode)', flush=True)

    (
        state,
        paradigm,
        collector,
        provider,
        buffer,
        optimizer,
        loss_fn,
        network,
    ) = _build_full_components(cfg)

    counters = {'n_collect_calls': 0, 'n_transitions': 0, 'n_train_steps': 0}
    profiler = cProfile.Profile()

    t_phase_start = time.monotonic()
    warmup_end = t_phase_start + args.warmup_seconds
    measure_end = warmup_end + measure_seconds
    final_end = measure_end + args.tail_seconds

    measure_wall = 0.0
    counters_at_warmup_end: dict = {}
    counters_at_measure_end: dict = {}

    try:
        # Phase 1: warmup — populate buffer + warm up imports/JIT/cache.
        # No profiler, counters reset at warmup_end snapshot boundary.
        while time.monotonic() < warmup_end:
            _run_one_iter(
                state,
                cfg,
                paradigm,
                collector,
                provider,
                buffer,
                optimizer,
                loss_fn,
                network,
                counters,
            )

        counters_at_warmup_end = dict(counters)

        # Phase 2: measure — cProfile.enable, count delta.
        profiler.enable()
        t_measure_start = time.monotonic()
        try:
            while time.monotonic() < measure_end:
                _run_one_iter(
                    state,
                    cfg,
                    paradigm,
                    collector,
                    provider,
                    buffer,
                    optimizer,
                    loss_fn,
                    network,
                    counters,
                )
        finally:
            t_measure_end = time.monotonic()
            profiler.disable()
            measure_wall = t_measure_end - t_measure_start

        counters_at_measure_end = dict(counters)

        # Phase 3: tail — run out the clock (no profiler, no count).
        while time.monotonic() < final_end:
            _run_one_iter(
                state,
                cfg,
                paradigm,
                collector,
                provider,
                buffer,
                optimizer,
                loss_fn,
                network,
                counters,
            )
    finally:
        collector.close()

    profiler.dump_stats(args.prof_output)

    total_wall = time.monotonic() - t_phase_start
    delta_collect = counters_at_measure_end['n_collect_calls'] - counters_at_warmup_end['n_collect_calls']
    delta_trans = counters_at_measure_end['n_transitions'] - counters_at_warmup_end['n_transitions']
    delta_train = counters_at_measure_end['n_train_steps'] - counters_at_warmup_end['n_train_steps']

    transitions_per_s = delta_trans / measure_wall if measure_wall > 0 else 0.0
    train_steps_per_s = delta_train / measure_wall if measure_wall > 0 else 0.0
    trans_per_train_step = (delta_trans / delta_train) if delta_train > 0 else 0.0

    print()
    print('=== profile_train summary ===')
    print(f'  cfg: {args.cfg}')
    print(f'  total_wall_s: {total_wall:.2f}')
    print(f'  warmup_s: {args.warmup_seconds:.1f} (discarded)')
    print(f'  measure_s: {measure_wall:.2f}')
    print(f'  tail_s: {args.tail_seconds:.1f} (discarded)')
    print()
    print('[measured window only]')
    print(f'  n_collect_calls: {delta_collect}')
    print(f'  n_transitions: {delta_trans}')
    print(f'  n_train_steps: {delta_train}')
    print(f'  transitions_per_s: {transitions_per_s:.2f}')
    print(f'  train_steps_per_s: {train_steps_per_s:.2f}')
    print(f'  trans_per_train_step: {trans_per_train_step:.2f}')
    print(f'  prof_output: {args.prof_output}')
    print()
    print(f'=== Top {args.top_hotspots} hotspots (cumulative time) ===')
    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    stats.print_stats(args.top_hotspots)
    print(s.getvalue())


if __name__ == '__main__':
    main()
