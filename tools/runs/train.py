"""tools.runs.train — single-command atomic lifecycle entry shell.

Sole entry point for training under the 2026-05-18 ``tools/runs/``
clean-slate redesign (spec
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§Architecture 行 24-74).

Phase implementations live in :mod:`tools.runs._train` sub-package
(``_helpers/`` precedent from T-04). This shell is argparse + main
dispatch only — it re-exports :class:`SetupState` and selected
internals so existing tests / future Phase B/C helpers can import
either ``tools.runs.train`` (public surface) or
``tools.runs._train.<phase>`` (internal phase modules).

Lifecycle phases:

- Phase A (T-08): steps 0-3 — validate + capture + resolve + mkdir
- Phase B (T-09): steps 4-5 — write cfg_leaf.toml + cfg_resolved.toml + metadata.toml
- Phase C (T-10): steps 6-7 — run train + close metadata
- Phase D (T-11+): paradigm dispatch / resume / authoritative host

T-08 ``main()`` calls Phase A then prints a stub and exits 0. T-09
inserts the Phase B call between Phase A success and the stub. T-10
replaces the stub with Phase C (run + close metadata) so ``main()``
now runs Phase A → B → C and returns Phase C's process exit code
(spec §Exit codes 行 247-257).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tools.runs._host import RemoteCfg, is_local_host, load_remote_from_cfg
from tools.runs._ssh import ssh_forward

# Re-exports: keep public ``tools.runs.train.<symbol>`` surface stable
# for tests that import e.g. ``train_mod.SetupState`` /
# ``train_mod._phase_a_setup`` directly. The actual definitions live in
# :mod:`tools.runs._train.setup`; monkeypatching the UTC ts source or
# the SetupState ctor must target ``_train.setup`` (the call site),
# not this shell. Underscored re-exports are kept to preserve the
# public ``train_mod._<name>`` surface that tests use.
from tools.runs._train.setup import (  # noqa: F401
    SetupState,
    _extract_leaf_label,
    _RUN_LABEL_RE,
    _validate_run_label,
    _verify_authoritative_host,
    _verify_repo_root,
    phase_a_setup as _phase_a_setup,
)
from tools.runs._train.resume import (  # noqa: F401
    phase_a_resume as _phase_a_resume,
)
from tools.runs._train.snapshot import (  # noqa: F401
    phase_b_write_cfg_metadata as _phase_b_write_cfg_metadata,
)
from tools.runs._train.run import (  # noqa: F401
    _run_train_placeholder,
    phase_c_run_train_and_close as _phase_c_run_train_and_close,
)

__all__ = [
    'SetupState',
    'main',
]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='tools.runs.train',
        description=(
            'Atomic train lifecycle (clean-slate redesign): allocate NNN, mkdir '
            'per-run dir, snapshot cfg, write metadata, run train, close metadata. '
            'T-08-T-10 ship steps 0-7 (placeholder train); T-11 swaps in real '
            'paradigm dispatch over the same Phase C stub.'
        ),
    )
    parser.add_argument('cfg', type=str, help='path to TOML cfg')
    parser.add_argument(
        '--override',
        action='append',
        default=[],
        metavar='KEY=VALUE',
        help='dotted-key override applied post-extends (repeatable)',
    )
    parser.add_argument(
        '--resume',
        type=str,
        default=None,
        help=(
            'ckpt path to resume from (T-12). Infers artifacts_dir from '
            '<ckpt>.parent.parent; reuses NNN; allocates cfg_resolved_v<N>; '
            'transitions metadata.status to running via the resume schema '
            'exception ({done,failed,killed,unknown,running} → running).'
        ),
    )
    return parser.parse_args(argv)


def _dispatch_remote(remote: RemoteCfg, args: argparse.Namespace) -> int:
    """P3 cfg-remote branch — auto-sync local→remote then ssh forward the
    full lifecycle to the remote box。No local NNN allocation, no local
    artifacts/<run>/ mkdir — the remote runs the same ``tools.runs.train``
    main() with ``cfg [meta].host == 'remote'`` + ``hostname`` matching
    its own ``socket.gethostname()``, hits the loopback branch via
    ``is_local_host``, and executes Phase A → B → C locally on the
    remote box (artifacts live there)。

    User pulls ckpts afterwards via ``tools.runs.pull cfg.toml <run-label>``。

    Sync subprocess is invoked via ``python -m tools.runs._remote_sync``
    (KISS — reuse the CLI rather than refactor a sync_files() helper);
    failure aborts before the train forward so a partially-stale remote
    tree never starts a run. ssh_forward streams stdout/stderr in
    real-time (Popen-based pump) because train is long-running and
    silence ≠ progress; the forward target's exit code is the local
    return value (Phase C close-metadata + 0/1/3 semantics, propagated
    unchanged from the remote side)。
    """
    sync_argv = [sys.executable, '-m', 'tools.runs._remote_sync', args.cfg]
    print(f'[train.remote] auto-sync: {" ".join(sync_argv)}', file=sys.stderr)
    sync = subprocess.run(sync_argv)
    if sync.returncode != 0:
        print(
            f'[train.remote] sync failed (rc={sync.returncode}), aborting',
            file=sys.stderr,
        )
        return sync.returncode

    extra: list[str] = []
    for ovr in args.override:
        extra.extend(['--override', ovr])
    if args.resume:
        extra.extend(['--resume', args.resume])

    print(
        f'[train.remote] ssh forward tools.runs.train → {remote.ssh}',
        file=sys.stderr,
    )
    return ssh_forward(remote, 'tools.runs.train', Path(args.cfg), extra, stream=True)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # P3 cfg-driven dispatch: if cfg targets a remote box (and we're NOT
    # currently on it via loopback hostname), auto-sync + ssh forward
    # the entire lifecycle. cfg schema violations raise ValueError —
    # let them propagate uncaught so the error is visible (consistent
    # with the other 6 cfg-driven tools, none of which swallow schema
    # errors). All-local + loopback both fall through to the original
    # atomic lifecycle below. Missing-cfg files are NOT pre-checked
    # here so that Phase A's SystemExit(2) + spec-worded error message
    # remains the single source of "cfg file missing" diagnostics.
    cfg_path = Path(args.cfg)
    if cfg_path.is_file():
        remote = load_remote_from_cfg(cfg_path)
        if not is_local_host(remote):
            assert remote is not None  # narrowed by is_local_host
            return _dispatch_remote(remote, args)

    try:
        if args.resume:
            # Resume path: reuse existing artifacts_dir, bump cfg_resolved_version,
            # write status='running' via the resume schema exception (CRIT-2-A).
            # No new NNN allocation, no per-run dir mkdir.
            state = _phase_a_resume(args)
        else:
            # Fresh path: allocate NNN under flock, mkdir per-run dir,
            # cfg_resolved_version=1.
            state = _phase_a_setup(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI boundary
        print(f'tools.runs.train: setup failed: {exc}', file=sys.stderr)
        return 2

    # Phase B: cfg_leaf.toml + cfg_resolved.toml + metadata.toml (status='running').
    # Failure path internally rmtree's the orphan dir + raises SystemExit(2)
    # — we let that propagate (the SystemExit handler in caller code, or
    # python interpreter top-level, prints the captured stderr). Other
    # unexpected exceptions are caught + mapped to exit 2 the same way as
    # Phase A above.
    try:
        _phase_b_write_cfg_metadata(state, Path(args.cfg))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI boundary
        print(f'tools.runs.train: cfg/metadata snapshot failed: {exc}', file=sys.stderr)
        return 2

    # Phase C: run train (T-10 stub; T-11 real paradigm dispatch) +
    # close metadata. Phase C is the boundary that owns its own exit
    # code mapping (spec §Exit codes 0/1/3) and never raises SystemExit
    # back out — exceptions there map to exit 3 (final write failure)
    # so we always have a deterministic numeric return value here.
    return _phase_c_run_train_and_close(state)


if __name__ == '__main__':
    sys.exit(main())
