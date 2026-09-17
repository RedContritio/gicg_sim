"""Single-actor DMC profile harness — cProfile + per-actor fps measurement.

Usage (Mac dev):

    .venv/bin/python -m tools.dmc.profile_actor --cfg configs/dmc/smoke.toml --duration-seconds 60

Usage (Windows X3D — the real target for ≥ 1200 fps):

    .venv/bin/python -m tools.runs.exec configs/dmc/smoke.toml -- .venv/Scripts/python.exe -m tools.dmc.profile_actor --cfg configs/dmc/smoke.toml --duration-seconds 300

Outputs:
- ``actor.prof`` (cProfile binary) — view with ``snakeviz actor.prof``
- stdout: per-actor fps + top 15 cumulative-time hotspots

Target verify (Windows X3D only):
- Per-actor fps ≥ 1200 → PASS criteria

Mac data: baseline for hotspot identification + cross-platform delta,
NOT the production fps target.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import time
from pathlib import Path
from typing import Any

from training.core.actor._mp_helpers import harden_child_env


def _build_serial_components(cfg: Any) -> tuple[Any, Any, Any]:
    """Mirror tools.runs._train.dispatch.run_paradigm_train construction
    shape for the **serial actor loop only** — no optimizer / loss / buffer.

    Returns (collector, network, provider) ready for the loop.
    """
    from training.core.actor.network_provider import LocalNetworkProvider
    from training.core.env_factory import make_env_factory
    from training.paradigms import resolve as resolve_paradigm

    paradigm = resolve_paradigm(cfg.meta.paradigm)
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)

    # Build network + opp_pool exactly as dispatch does.
    network = paradigm.make_network(cfg)
    opp_pool = paradigm.make_opponent_pool(cfg, network) if hasattr(paradigm, 'make_opponent_pool') else None
    collector = paradigm.make_collector(cfg, env_factory, network, opp_pool)
    provider = LocalNetworkProvider(network, device=cfg.meta.device)
    return collector, network, provider


def _run_one_actor_for_duration(cfg: Any, duration_seconds: int) -> tuple[int, int]:
    """Run serial DMC collector for up to ``duration_seconds`` wall.

    Returns ``(n_transitions_collected, n_collect_calls)``.
    """
    collector, _network, provider = _build_serial_components(cfg)
    n_trans = 0
    n_calls = 0
    try:
        t_start = time.monotonic()
        deadline = t_start + duration_seconds
        # Single-episode-per-call mirrors DMCParadigm.step_schedule cadence
        # (StepPlan.n_episodes=1 in steady state).
        while time.monotonic() < deadline:
            out = collector.collect(1, provider)
            n_trans += int(out.n_units)
            n_calls += 1
    finally:
        collector.close()
    return n_trans, n_calls


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='DMC single-actor cProfile harness (per-actor fps + hotspot identification).',
    )
    p.add_argument('--cfg', required=True, type=Path, help='Path to DMC TOML cfg.')
    p.add_argument(
        '--duration-seconds',
        type=int,
        default=60,
        help='Wall budget for the collect loop (default 60).',
    )
    p.add_argument(
        '--prof-output',
        type=str,
        default='actor.prof',
        help='cProfile binary output path (default actor.prof in CWD).',
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

    # Mirror real actor process startup — single-actor profile should
    # not oversubscribe the box. harden_child_env is idempotent.
    harden_child_env()

    from training.core.config.loader import load_cfg

    cfg = load_cfg(args.cfg, overrides=[])
    if cfg.meta.paradigm != 'dmc':
        raise SystemExit(
            f'profile_actor: cfg.meta.paradigm must be "dmc", got {cfg.meta.paradigm!r}',
        )

    profiler = cProfile.Profile()
    profiler.enable()
    t_start = time.monotonic()
    try:
        n_trans, n_calls = _run_one_actor_for_duration(cfg, args.duration_seconds)
    finally:
        wall = time.monotonic() - t_start
        profiler.disable()
        profiler.dump_stats(args.prof_output)

    fps = n_trans / wall if wall > 0 else 0.0
    print()
    print('=== profile_actor summary ===')
    print(f'  cfg: {args.cfg}')
    print(f'  wall_duration_s: {wall:.2f}')
    print(f'  n_collect_calls: {n_calls}')
    print(f'  n_transitions: {n_trans}')
    print(f'  per_actor_fps (transitions/s): {fps:.1f}')
    print(f'  prof_output: {args.prof_output}')
    print()
    print(f'=== Top {args.top_hotspots} hotspots (by cumulative time) ===')
    # Print into a buffer so stdout ordering stays deterministic when
    # caller redirects to a file.
    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    stats.print_stats(args.top_hotspots)
    print(s.getvalue())


if __name__ == '__main__':
    main()
