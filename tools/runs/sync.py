"""``tools.runs.sync`` — rsync wrapper for cross-host artifacts metadata.

Clean-slate rewrite per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``:
§Cross-host sync 行 326-331 / §Conflict HIGH-2-E 行 333-339 / §Case-collide
CRIT-5-A 行 341-346 (T-19) / §Authoritative HIGH-2-D 行 348-356 (T-19) /
§Include-exclude 行 357-371 / §IPv6 HIGH-6-B 行 441 / 行 493 (T-19).

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

    .venv/bin/python -m tools.runs.sync push <user@host:path/>
    .venv/bin/python -m tools.runs.sync pull <user@host:path/>
    .venv/bin/python -m tools.runs.sync init-authoritative

T-20 scope: integration tests (real rsync + ssh).
"""

from __future__ import annotations

import argparse
import re
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.runs._helpers.sync_extras import (
    REMOTE_RE_PATTERN,
    CaseCollideError,
    detect_case_collisions,
    init_authoritative,
)
from tools.runs._helpers import sync_scan as _ss

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

# Hardcoded; user override forbidden (stray ``--exclude=*`` removal could
# leak GB-scale ckpt across a slow link). rsync = first-match-wins.
RSYNC_FLAGS: tuple[str, ...] = (
    '-av',
    '--include=artifacts/',
    '--include=artifacts/*/',
    '--include=artifacts/*/metadata.toml',
    '--include=artifacts/*/cfg_resolved*.toml',
    '--include=artifacts/*/cfg_leaf*.toml',
    '--exclude=artifacts/.authoritative_host',
    '--exclude=artifacts/.run_id_lock',
    '--exclude=artifacts/*/.metadata_lock',
    '--exclude=*',
)

# Strict ``user@host:path/`` form; host = alphanum hostname / IPv4, or
# IPv6 bracket form (spec §HIGH-6-B). Pattern source lives in sync_extras.
_REMOTE_RE = re.compile(REMOTE_RE_PATTERN)


class SyncConflict(RuntimeError):
    """Raised when one or more NNN dirs have equal ``metadata.timestamp``
    on local + remote (HIGH-2-E tie). User must manually resolve."""


@dataclass(frozen=True)
class ConflictRow:
    """One per-NNN comparison result."""

    nnn: str
    local_ts: str | None  # None if only remote has the NNN
    remote_ts: str | None  # None if only local has the NNN
    resolution: str  # 'local_newer' / 'remote_newer' / 'equal' / 'only_local' / 'only_remote'


def _validate_remote(remote: str) -> None:
    """Strict ``user@host:path/`` form. macOS local paths with ``:`` and
    bare ``host:path/`` (no user) are rejected. IPv6 bracket form
    (``user@[::1]:/path/``) is accepted (spec §HIGH-6-B)."""
    if not _REMOTE_RE.match(remote):
        raise ValueError(
            f'remote {remote!r} must be of form user@host:path/ '
            '(user@host + colon + path + trailing slash; IPv6 bracket form OK)'
        )


def detect_conflicts(local: dict[str, str], remote: dict[str, str]) -> list[ConflictRow]:
    """Pair every NNN seen on either side; compare ``metadata.timestamp``.
    Result sorted by NNN asc. ``resolution`` ∈ {local_newer, remote_newer,
    equal (HIGH-2-E tie → upstream raises), only_local, only_remote}."""
    rows: list[ConflictRow] = []
    for nnn in sorted(set(local) | set(remote)):
        l_ts = local.get(nnn)
        r_ts = remote.get(nnn)
        if l_ts is None:
            rows.append(ConflictRow(nnn=nnn, local_ts=None, remote_ts=r_ts, resolution='only_remote'))
        elif r_ts is None:
            rows.append(ConflictRow(nnn=nnn, local_ts=l_ts, remote_ts=None, resolution='only_local'))
        elif l_ts == r_ts:
            rows.append(ConflictRow(nnn=nnn, local_ts=l_ts, remote_ts=r_ts, resolution='equal'))
        elif l_ts > r_ts:
            rows.append(ConflictRow(nnn=nnn, local_ts=l_ts, remote_ts=r_ts, resolution='local_newer'))
        else:
            rows.append(ConflictRow(nnn=nnn, local_ts=l_ts, remote_ts=r_ts, resolution='remote_newer'))
    return rows


def _excludes_for_conflicts(rows: list[ConflictRow], *, direction: str) -> list[str]:
    """Build ``--exclude=artifacts/*_<NNN>_*/`` for losing-side NNN.

    push → exclude ``remote_newer`` rows (don't overwrite remote-fresher).
    pull → exclude ``local_newer`` rows (symmetric). ``equal`` raises
    upstream; ``only_*`` and the winning side need no exclude. ``direction``
    is pre-validated by callers (no defensive recheck per CLAUDE.md §2).
    """
    bad = 'remote_newer' if direction == 'push' else 'local_newer'
    return [f'--exclude=artifacts/*_{row.nnn}_*/' for row in rows if row.resolution == bad]


def build_rsync_cmd(
    direction: str,
    remote: str,
    *,
    root: Path,
    conflict_rows: list[ConflictRow] | None = None,
) -> list[str]:
    """rsync argv. Conflict ``--exclude`` flags precede include flags
    (first-match-wins). push = local → remote; pull = remote → local."""
    if direction not in ('push', 'pull'):
        raise ValueError(f'direction must be push|pull, got {direction!r}')
    _validate_remote(remote)
    local_arg = f'{root}/'  # trailing slash → merge into remote
    extra_excludes = _excludes_for_conflicts(conflict_rows or [], direction=direction)
    # Conflict-exclude FIRST so it matches before any include rule below.
    cmd: list[str] = ['rsync', *extra_excludes, *RSYNC_FLAGS]
    if direction == 'push':
        cmd += [local_arg, remote]
    else:
        cmd += [remote, local_arg]
    return cmd


def _ensure_local_artifacts_dir(root: Path) -> None:
    """Create ``<root>/artifacts/`` if missing (rsync needs dest dir to exist)."""
    (root / 'artifacts').mkdir(parents=True, exist_ok=True)


def sync(
    *,
    direction: str,
    remote: str,
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
    _validate_remote(remote)
    if runner is None:
        runner = subprocess.run

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
        result = runner(cmd, capture_output=True, text=True, check=False)
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
        'remote',
        nargs='?',
        default=None,
        help='e.g. dev@192.168.31.56:/d/gicg_dev/ (omit for init-authoritative)',
    )
    ap.add_argument('--root', default=None, help='override local repo root (testing only)')
    ap.add_argument('--dry-run', action='store_true', help='print rsync cmd without executing')
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else Path.cwd()

    if args.direction == 'init-authoritative':
        if args.remote is not None:
            print('tools.runs.sync: init-authoritative takes no remote argument', file=sys.stderr)
            return 1
        marker = init_authoritative(root)
        print(f'authoritative host set: {socket.gethostname()} ({marker})', file=sys.stderr)
        return 0

    if args.remote is None:
        print(f'tools.runs.sync: {args.direction} requires a remote argument', file=sys.stderr)
        return 1
    try:
        result = sync(
            direction=args.direction,
            remote=args.remote,
            root=root,
            dry_run=args.dry_run,
        )
    except (ValueError, RuntimeError, SyncConflict, CaseCollideError) as e:
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
