"""``tools.runs.sync`` — rsync wrapper for run metadata and config snapshots.

Clean-slate rewrite per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`` (主卷)
+ ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design-rollout.md`` (续卷):
§Cross-host sync / §Conflict HIGH-2-E / §Case-collide
CRIT-5-A (T-19) / §Authoritative HIGH-2-D (T-19) /
§Include-exclude / §IPv6 HIGH-6-B (T-19).

Transferred: ``artifacts/*/{metadata.toml,cfg_resolved*.toml,cfg_leaf*.toml}``.
Never transferred (excluded): ``artifacts/{.authoritative_host,.run_id_lock}``,
``artifacts/*/.metadata_lock``, plus all of ``ckpts/`` / ``metrics.jsonl`` /
``tb/`` (catch-all ``--exclude=*``).

Conflict resolution: per-NNN ``metadata.timestamp`` compare (not mtime —
clock-drift unsafe); losing side gets ``--exclude=`` to skip + stderr warn;
exact tie raises :class:`SyncConflict`. Case-collide: pre-flight scan
local+remote dir names; if two differ only in case, raise
:class:`CaseCollideError` before rsync runs (macOS APFS ↔ Linux ext4 guard).

CLI::

    .venv/bin/python -m tools.runs.sync push <cfg.toml>
    .venv/bin/python -m tools.runs.sync pull <cfg.toml>
    .venv/bin/python -m tools.runs.sync init-authoritative

"""

from __future__ import annotations

import argparse
import shlex
import socket
import sys
from pathlib import Path

from tools.runs._host import RemoteCfg, is_local_host, load_remote_from_cfg, rsync_run
from tools.runs._helpers import sync_conflicts as _sc
from tools.runs._helpers import sync_scan as _ss
from tools.runs._helpers.sync_extras import (
    CaseCollideError,
    detect_case_collisions,
    init_authoritative,
)

# Conflict detection + rsync argv construction live in
# ``_helpers/sync_conflicts.py``; re-exported through this module because the
# sync test-suite reaches them as ``sync.<name>``.
RSYNC_FLAGS = _sc.RSYNC_FLAGS
SyncConflict = _sc.SyncConflict
ConflictRow = _sc.ConflictRow
build_rsync_cmd = _sc.build_rsync_cmd
detect_conflicts = _sc.detect_conflicts
_validate_remote = _sc.validate_remote
_remote_endpoint = _sc.remote_endpoint

_fetch_remote_find_text = _ss.fetch_remote_find_text
_parse_remote_dir_names = _ss.parse_remote_dir_names
_parse_remote_find_output = _ss.parse_remote_find_output  # noqa: F841 (kept for test re-export below)
_scan_local_dir_names = _ss.scan_local_dir_names
_scan_local_timestamps = _ss.scan_local_timestamps
_scan_remote_timestamps = _ss.scan_remote_timestamps  # noqa: F841  back-compat re-export for tests

# Public surface — tests poke ``_scan_local_timestamps`` /
# ``_parse_remote_find_output`` via the aliased re-exports above.
__all__ = [
    'RSYNC_FLAGS',
    'SyncConflict',
    'CaseCollideError',
    'ConflictRow',
    'build_rsync_cmd',
    'detect_conflicts',
    'detect_case_collisions',
    'init_authoritative',
    'sync',
    'main',
]


def _verify_repo_root(root: Path) -> None:
    """Fail loud if *root* is not the repo root (e.g. user ran from a subdir)."""
    if not (root / '.git').exists():
        raise RuntimeError(
            f'sync root {root} has no .git/ — are you running from a subdirectory? '
            f'Run from the repo root or pass --root explicitly.'
        )


def _ensure_local_artifacts_dir(root: Path) -> None:
    """Create ``<root>/artifacts/`` if missing (rsync needs dest dir to exist)."""
    (root / 'artifacts').mkdir(parents=True, exist_ok=True)


def sync(
    *,
    direction: str,
    remote: RemoteCfg,
    root: Path,
    runner=None,
    ssh_runner=None,
    dry_run: bool = False,
) -> list[str] | int:
    """Run sync. ``dry_run=True`` returns the rsync argv list without invoking.

    Steps: scan local + remote (one SSH fetch reused) → case-collide raise
    pre-flight → per-NNN conflict detect → losing-side ``--exclude`` + warn
    → build cmd → dry-run return / exec. ``runner`` injects rsync subprocess;
    ``ssh_runner`` injects the SSH call.
    """
    if direction not in ('push', 'pull'):
        raise ValueError(f'direction must be push|pull, got {direction!r}')
    _verify_repo_root(root)
    if runner is None:
        runner = rsync_run

    local_ts = _scan_local_timestamps(root)
    remote_text = _fetch_remote_find_text(remote, runner=ssh_runner)
    remote_ts = _parse_remote_find_output(remote_text)

    # Spec §CRIT-5-A — pre-flight case-collide; raise before rsync runs so
    # macOS APFS doesn't silently overwrite ``_DMC`` vs ``_dmc`` siblings.
    local_names = _scan_local_dir_names(root)
    remote_names = _parse_remote_dir_names(remote_text)
    collisions = detect_case_collisions(local_names + remote_names)
    if collisions:
        pairs = ', '.join(f'{a!r} <-> {b!r}' for a, b in collisions)
        raise CaseCollideError(
            f'artifacts dir name(s) collide under case-insensitive fs (macOS APFS): {pairs}. '
            'Rename one side before retrying sync.'
        )

    conflicts = detect_conflicts(local_ts, remote_ts)

    ties = [c for c in conflicts if c.resolution == 'equal']
    if ties:
        nnn_list = ', '.join(c.nnn for c in ties)
        raise SyncConflict(
            f'timestamp tie on NNN [{nnn_list}] — same metadata.timestamp on '
            'both sides; manually resolve (e.g. inspect cfg_resolved + rename '
            'one dir) and retry'
        )

    bad_resolution = 'remote_newer' if direction == 'push' else 'local_newer'
    for c in conflicts:
        if c.resolution == bad_resolution:
            print(
                f'tools.runs.sync: skipping NNN {c.nnn}: {bad_resolution} '
                f'(local_ts={c.local_ts} remote_ts={c.remote_ts})',
                file=sys.stderr,
            )

    _ensure_local_artifacts_dir(root)
    cmd = build_rsync_cmd(direction, remote, root=root, conflict_rows=conflicts)

    if dry_run:
        return cmd

    try:
        result = runner(cmd)
    except FileNotFoundError as e:
        raise RuntimeError(f'rsync not found on PATH ({e}); install rsync first') from e
    if result.returncode != 0:
        raise RuntimeError(f'rsync {direction} failed (exit {result.returncode}): {result.stderr.strip()}')
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith('\n'):
            sys.stdout.write('\n')
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('direction', choices=['push', 'pull', 'init-authoritative'])
    ap.add_argument(
        'cfg',
        nargs='?',
        default=None,
        help='training cfg.toml; [meta].host + [remote].profile select the host (omit for init-authoritative)',
    )
    ap.add_argument('--root', default=None, help='override local repo root (testing only)')
    ap.add_argument('--dry-run', action='store_true', help='print rsync cmd without executing')
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else Path.cwd()

    if args.direction == 'init-authoritative':
        if args.cfg is not None:
            print('tools.runs.sync: init-authoritative takes no cfg argument', file=sys.stderr)
            return 1
        marker = init_authoritative(root)
        print(f'authoritative host set: {socket.gethostname()} ({marker})', file=sys.stderr)
        return 0

    if args.cfg is None:
        print(f'tools.runs.sync: {args.direction} requires a cfg argument', file=sys.stderr)
        return 1
    try:
        remote = load_remote_from_cfg(Path(args.cfg))
        if is_local_host(remote):
            print('tools.runs.sync: cfg host is local — nothing to sync', file=sys.stderr)
            return 0
        assert remote is not None
        result = sync(
            direction=args.direction,
            remote=remote,
            root=root,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, RuntimeError, SyncConflict, CaseCollideError) as e:
        print(f'tools.runs.sync: {e}', file=sys.stderr)
        return 1
    if args.dry_run:
        assert isinstance(result, list)
        print(' '.join(shlex.quote(x) for x in result))
        return 0
    assert isinstance(result, int)
    return result


if __name__ == '__main__':
    sys.exit(main())
