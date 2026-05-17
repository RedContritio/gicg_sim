"""Unified training entry — `python -m tools.run <cfg.toml>`.

Dispatches based on `cfg.meta.paradigm` to the registered Paradigm
adapter under `training/paradigms/<name>/`. Sole training entry point
since FU-W4 retired the per-paradigm legacy launchers
(historical: tools/dmc_train.py, tools/launch_config.py for AZ,
tools/ppo_launch.py, tools/run_cfr.py — all archive-removed
2026-05-16).

CLI:
    python -m tools.run configs/dmc_stage3_smoke_v2.toml
    python -m tools.run configs/x.toml --override paradigm.epsilon=0.1
    python -m tools.run configs/x.toml --run-id s001   # link to registered run

When ``--run-id`` is given the registered ``RunMetadata.timestamp`` is
converted to local ``%Y%m%d%H%M`` and used as the artifacts-dir prefix
— single-sourced timestamp across register + ckpt dir (otherwise the
two are independent now() calls that may straddle e.g. midnight UTC).
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.pipeline import run_pipeline
from training.paradigms import resolve as resolve_paradigm


def _metadata_timestamp_to_dir_prefix(ts: str) -> str:
    """Convert RunMetadata.timestamp (iso8601 with TZ) to artifacts
    dir prefix in `%Y%m%d%H%M` UTC form. UTC chosen so the dir prefix
    is identical on every host that picks up the same metadata —
    `.astimezone()` (per-host local) would defeat the single-source
    intent under cross-tz dev/CI."""
    dt = datetime.datetime.fromisoformat(ts)
    return dt.astimezone(datetime.timezone.utc).strftime('%Y%m%d%H%M')


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog='tools.run', description=__doc__)
    parser.add_argument('config', type=str, help='path to TOML cfg')
    parser.add_argument(
        '--override',
        action='append',
        default=[],
        help='key.path=value override (repeatable)',
    )
    parser.add_argument('--resume', type=str, default=None, help='resume from ckpt path')
    parser.add_argument('--max-steps', type=int, default=None, help='cap on driver iter count (tests)')
    parser.add_argument(
        '--run-id',
        type=str,
        default=None,
        dest='run_id',
        help='registered run id (e.g. s001) — links train to RunMetadata, single-sourcing timestamp',
    )
    args = parser.parse_args(argv)

    if args.run_id:
        conflicting = [o for o in args.override if o.startswith('meta.run_label=')]
        if conflicting:
            print(
                '[tools.run] --override meta.run_label=... conflicts with --run-id '
                '(metadata.cfg_run_label snapshot already taken at register time). '
                'Re-register with `--cfg-run-label-override <slug>` or drop --run-id.',
                file=sys.stderr,
            )
            return 2

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f'[tools.run] config not found: {cfg_path}', file=sys.stderr)
        return 2

    artifacts_timestamp_local: str | None = None
    if args.run_id:
        from tools.runs import schema as runs_schema

        meta_path = runs_schema.run_path(args.run_id)
        if not meta_path.exists():
            print(
                f'[tools.run] run {args.run_id} not registered (no {meta_path}); '
                f'register first via `tools.runs.register --run-id {args.run_id} --cfg {cfg_path}`',
                file=sys.stderr,
            )
            return 2
        run_meta = runs_schema.load_file(meta_path)
        try:
            artifacts_timestamp_local = _metadata_timestamp_to_dir_prefix(run_meta.timestamp)
        except ValueError as e:
            print(f'[tools.run] run {args.run_id} timestamp malformed: {e}', file=sys.stderr)
            return 2
        print(f'[tools.run] linked to run {args.run_id} (artifacts ts={artifacts_timestamp_local} UTC)')

    print(f'[tools.run] loading cfg: {cfg_path}')
    cfg = load_cfg(cfg_path, overrides=list(args.override))
    print(
        f'[tools.run] paradigm={cfg.meta.paradigm} seed={cfg.meta.seed} '
        f'mode={cfg.pipeline.mode} run_label={cfg.meta.run_label}'
    )

    paradigm = resolve_paradigm(cfg.meta.paradigm)
    # obs_config_json=None — unified pipeline configs (DMC / PPO / CFR /
    # BC) don't carry ObsConfig; engine applies all-on shuffle defaults.
    # AZ legacy path goes through paradigms/az/train_loop/async_loop.py
    # which passes cfg.obs.to_engine_json() explicitly.
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)

    # Paradigm-supplied opponent pool. Built here so it lives in the
    # main process (driver doesn't know about OpponentPool type).
    opp_pool = None
    if hasattr(paradigm, 'make_opponent_pool'):
        # Defer network build to driver; opp_pool only needs the agent
        # cfg signature for its historical factory which is resolved
        # lazily on first historical sample.
        # We instantiate the network here so historical-factory closes
        # over the same AgentConfig the driver will use. Driver also
        # calls make_network internally; second build is harmless
        # (paradigm caches via self._network).
        network = paradigm.make_network(cfg)
        opp_pool = paradigm.make_opponent_pool(cfg, network)

    resume_path = Path(args.resume) if args.resume else None

    final_state = run_pipeline(
        cfg,
        paradigm,
        env_factory=env_factory,
        opp_pool=opp_pool,
        eval_server=None,  # P4: wire EvalServer when async + remote inference lands
        resume_from=resume_path,
        max_steps=args.max_steps,
        artifacts_timestamp_local=artifacts_timestamp_local,
    )

    print(
        f'[tools.run] final: step={final_state.step} '
        f'frames={final_state.total_transitions} '
        f'episodes={final_state.total_episodes} '
        f'train_steps={final_state.train_steps} '
        f'wall_s={final_state.wall_seconds:.1f}'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
