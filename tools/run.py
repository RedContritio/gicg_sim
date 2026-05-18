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
import hashlib
import json
import sys
from pathlib import Path

from training.core.config.loader import load_with_extends
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.pipeline import run_pipeline
from training.paradigms import resolve as resolve_paradigm


def _cfg_checksum(cfg_path: Path) -> str:
    """Extends-resolved canonical-JSON sha256, matching the format
    written by the retired legacy register CLI so on-disk
    ``metadata.cfg_checksum`` snapshots still compare correctly during
    the legacy-path drift guard. tools.run.py + this helper are slated
    for removal in T-23; do not adopt as a new public API."""
    merged = load_with_extends(cfg_path)
    canonical = json.dumps(merged, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return f'sha256:{hashlib.sha256(canonical.encode("utf-8")).hexdigest()}'


def _extract_run_label(cfg_path: Path) -> str | None:
    """Inlined from retired legacy register CLI's run_label extractor.
    Reads cfg's extends-resolved ``[meta].run_label`` field. Same caveat
    as ``_cfg_checksum``: dies with tools/run.py in T-23."""
    merged = load_with_extends(cfg_path)
    meta = merged.get('meta')
    if not isinstance(meta, dict):
        return None
    v = meta.get('run_label')
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError(f'cfg {cfg_path} meta.run_label must be a string, got {type(v).__name__}')
    return v


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

    artifacts_timestamp_utc: str | None = None
    if args.run_id:
        from tools.runs import schema as runs_schema

        meta_path = runs_schema.run_path(args.run_id)
        if not meta_path.exists():
            print(
                f'[tools.run] run {args.run_id} not registered (no {meta_path}); '
                f'the legacy register CLI is retired — start the run via '
                f'`tools.runs.train {cfg_path}` instead (it allocates NNN + creates metadata atomically)',
                file=sys.stderr,
            )
            return 2
        try:
            run_meta = runs_schema.load_file(meta_path)
        except ValueError as e:
            # schema.load_file now enforces M7 filename invariant + schema validation;
            # any ValueError here = corrupted metadata.
            print(f'[tools.run] run {args.run_id} metadata corrupted: {e}', file=sys.stderr)
            return 2

        # Guard cfg drift between register-time snapshot and current cfg file.
        # If user edits cfg after register, --run-id would silently train on the
        # mutated cfg while metadata.cfg_checksum still points at the old
        # snapshot — defeats C2's "register = pin truth" intent.
        #
        # Only checksum is compared (NOT cfg_run_label), because run_label can
        # legitimately differ from cfg via `register --cfg-run-label-override`
        # (Phase 2 AD4). Checksum subsumes run_label edits anyway — run_label
        # is part of the cfg → part of canonical JSON → part of checksum.
        # _cfg_checksum / _extract_run_label inlined above (T-21 retired
        # the legacy register CLI; this whole legacy path dies in T-23).
        current_checksum = _cfg_checksum(cfg_path)
        if current_checksum != run_meta.cfg_checksum:
            print(
                f'[tools.run] cfg drift: {cfg_path} checksum={current_checksum} '
                f'!= register-time {run_meta.cfg_checksum}. '
                f'Either revert cfg, or delete artifacts/runs/{args.run_id}.toml '
                f'and re-register.',
                file=sys.stderr,
            )
            return 2

        # Apply --cfg-run-label-override propagation: if metadata.cfg_run_label
        # differs from cfg.meta.run_label (i.e. user used register
        # --cfg-run-label-override), auto-inject the snapshot value as a
        # train-time override so artifacts_dir reflects register-time intent,
        # not the cfg's literal field.
        extracted_run_label = _extract_run_label(cfg_path)
        if extracted_run_label != run_meta.cfg_run_label:
            # If user already passed --override meta.run_label=, the earlier
            # conflict-check exited; reaching here means we're the only injector.
            args.override.append(f'meta.run_label={run_meta.cfg_run_label}')
            print(
                f'[tools.run] auto-applied --override meta.run_label={run_meta.cfg_run_label!r} '
                f'from register-time --cfg-run-label-override snapshot',
                file=sys.stderr,
            )

        try:
            artifacts_timestamp_utc = _metadata_timestamp_to_dir_prefix(run_meta.timestamp)
        except ValueError as e:
            print(f'[tools.run] run {args.run_id} timestamp malformed: {e}', file=sys.stderr)
            return 2
        print(f'[tools.run] linked to run {args.run_id} (artifacts ts={artifacts_timestamp_utc} UTC)')

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

    auto_status = 'done'
    auto_complete_failed = False
    final_state = None
    try:
        final_state = run_pipeline(
            cfg,
            paradigm,
            env_factory=env_factory,
            opp_pool=opp_pool,
            eval_server=None,  # P4: wire EvalServer when async + remote inference lands
            resume_from=resume_path,
            max_steps=args.max_steps,
            artifacts_timestamp_utc=artifacts_timestamp_utc,
        )
    except BaseException:
        auto_status = 'failed'
        raise
    finally:
        if args.run_id:
            # Wrap auto-complete in try/except so a metadata-write failure
            # (disk-full / _normalize_repo_relative rejecting an out-of-tree
            # resume parent / schema validate error) does NOT replace the
            # in-flight train exception per Python finally semantics.
            try:
                from training.core.checkpoint import CheckpointManager

                from tools.runs.complete import complete_from_train

                if args.resume:
                    # CheckpointManager.init_artifacts_dir(resume_from=...) returns
                    # Path(resume_from).parent — synthesize-from-formula would diverge.
                    actual_dir = Path(args.resume).parent
                else:
                    artifacts_root = Path(getattr(cfg.checkpoint, 'artifacts_root', 'artifacts'))
                    actual_dir = artifacts_root / CheckpointManager.compute_dir_name(
                        artifacts_timestamp_utc, cfg.meta.run_label
                    )
                wall = final_state.wall_seconds if final_state is not None else None
                complete_from_train(
                    run_id=args.run_id,
                    artifacts_dir=actual_dir,
                    status=auto_status,
                    wall_seconds=wall,
                )
            except Exception as e:  # noqa: BLE001 — must swallow to preserve train exception
                print(
                    f'[tools.run] auto-complete failed for run {args.run_id}: {e}; '
                    f'metadata may be stale, run `tools.runs.complete --run-id {args.run_id} --status {auto_status} --artifacts-dir <path>` manually',
                    file=sys.stderr,
                )
                auto_complete_failed = True

    print(
        f'[tools.run] final: step={final_state.step} '
        f'frames={final_state.total_transitions} '
        f'episodes={final_state.total_episodes} '
        f'train_steps={final_state.train_steps} '
        f'wall_s={final_state.wall_seconds:.1f}'
    )
    # Non-zero exit if metadata link was not closed — CI/cron must detect.
    return 3 if auto_complete_failed else 0


if __name__ == '__main__':
    sys.exit(main())
