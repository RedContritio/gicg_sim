"""``tools.runs.sync`` — rsync wrapper for cross-host artifacts metadata.

Clean-slate rewrite per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``:
- §Cross-host sync 设计 行 326-331
- §Conflict resolution HIGH-2-E 行 333-339
- §Include / exclude pattern 行 357-371

What gets transferred (rsync include):
    artifacts/*/metadata.toml
    artifacts/*/cfg_resolved*.toml       (含 v2/v3 ...)
    artifacts/*/cfg_leaf*.toml           (含 v2/v3 ...)

What NEVER transfers (rsync exclude / not matched):
    artifacts/.authoritative_host        host-local 不跨机
    artifacts/.run_id_lock               host-local lock
    artifacts/*/.metadata_lock           per-run lock 也不跨
    artifacts/*/ckpts/                   (数据大,跨机不必要)
    artifacts/*/metrics.jsonl
    artifacts/*/tb/
    (其他全部 by 末尾 ``--exclude=*``)

Conflict resolution (HIGH-2-E): per-NNN ``metadata.timestamp`` 字段比对,
不用 mtime(跨时区 / clock drift 不可靠)。push 时 local 新 → 覆盖 remote;
remote 新 → skip + stderr warn(通过给 rsync 加额外 ``--exclude`` 该 NNN
路径实现);timestamp 完全等 → raise SyncConflict + 列冲突 NNN(极罕见,
user 手动 resolve)。

CLI::

    .venv/bin/python -m tools.runs.sync push <user@host:path/>
    .venv/bin/python -m tools.runs.sync pull <user@host:path/>

T-18 scope: 仅 push/pull + flags + timestamp 比对。``init-authoritative``
子命令 / IPv6 regex / case-collide detection / integration tests 是 T-19/T-20.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.runs._helpers.sync_scan import (
    parse_remote_find_output as _parse_remote_find_output,  # noqa: F401  re-export for tests
)
from tools.runs._helpers.sync_scan import (
    scan_local_timestamps as _scan_local_timestamps,
)
from tools.runs._helpers.sync_scan import (
    scan_remote_timestamps as _scan_remote_timestamps,
)

# Public surface — tests still poke ``_scan_local_timestamps`` /
# ``_parse_remote_find_output`` via aliased re-exports above.
__all__ = [
    'RSYNC_FLAGS',
    'SyncConflict',
    'ConflictRow',
    'build_rsync_cmd',
    'detect_conflicts',
    'sync',
    'main',
]

# Hardcoded — user override forbidden per spec risk note (a stray
# ``--exclude=*`` removal could leak GB-scale ckpt across a slow link).
# Order matters: rsync applies the first matching include/exclude.
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

# Remote URL — strict ``user@host:path/`` (host: alphanum + dot + dash, ASCII).
# IPv6 ``user@[::1]:/path/`` form is explicitly out of scope for T-18 and
# rejected (T-19 will widen). Trailing ``/`` is required (rsync merges
# contents only with trailing slash).
_REMOTE_RE = re.compile(r'^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:.*/$')


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
    bare ``host:path/`` (no user) are rejected. IPv6 ``[::1]`` form is
    T-19 scope and rejected here."""
    if not _REMOTE_RE.match(remote):
        raise ValueError(
            f'remote {remote!r} must be of form user@host:path/ '
            '(user@host + colon + path + trailing slash; IPv6 not yet supported)'
        )


def detect_conflicts(local: dict[str, str], remote: dict[str, str]) -> list[ConflictRow]:
    """Pair every NNN seen in either side; compare ``metadata.timestamp``.

    Returns list sorted by nnn asc. Each row:
    - ``'local_newer'`` — local ts > remote ts (push: ok / pull: skip)
    - ``'remote_newer'`` — remote ts > local ts (push: skip / pull: ok)
    - ``'equal'`` — bit-equal ts string (HIGH-2-E tie → must raise upstream)
    - ``'only_local'`` — local has it, remote doesn't (push: transfer)
    - ``'only_remote'`` — remote has it, local doesn't (pull: transfer)
    """
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
    """Build extra ``--exclude=`` flags for NNN dirs we must NOT touch.

    push direction → exclude every ``remote_newer`` NNN (don't overwrite).
    pull direction → exclude every ``local_newer`` NNN (same logic, reverse).
    ``equal`` is handled by the SyncConflict raise upstream; ``only_*`` and
    the winning side need no exclude.

    Pattern: ``artifacts/*_<NNN>_*/`` matches ``<ts>_<NNN>_<label>``.
    Listed BEFORE generic ``--exclude=*`` they win (rsync first-match-wins).

    ``direction`` is pre-validated by the sole caller ``build_rsync_cmd``
    (and transitively by ``sync()``); no defensive recheck here (CLAUDE.md
    §2 dead-defensive ban).
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
    """Assemble the rsync argv list.

    Conflict-derived ``--exclude`` flags come BEFORE the include flags so
    they win (rsync first-match-wins). Direction controls argv order:
    ``push = local → remote`` / ``pull = remote → local``.
    """
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
    """Run sync. With ``dry_run=True`` return the rsync argv list and
    skip actually invoking it (used by tests + ``--dry-run`` CLI flag).

    Steps:
    1. Scan local + remote (via SSH) metadata.toml timestamps.
    2. Detect per-NNN conflicts; raise SyncConflict on any ``equal`` tie.
    3. For losing-side NNN (remote_newer on push / local_newer on pull),
       stderr warn + add to rsync ``--exclude`` so they don't transfer.
    4. Build cmd; if dry_run, return cmd; else exec via runner.

    ``runner`` injects ``subprocess.run`` for rsync. ``ssh_runner`` injects
    the SSH cmd used to fetch remote timestamps.
    """
    if direction not in ('push', 'pull'):
        raise ValueError(f'direction must be push|pull, got {direction!r}')
    _validate_remote(remote)
    if runner is None:
        runner = subprocess.run

    local_ts = _scan_local_timestamps(root)
    remote_ts = _scan_remote_timestamps(remote, runner=ssh_runner)
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
    ap.add_argument('direction', choices=['push', 'pull'])
    ap.add_argument('remote', help='e.g. dev@192.168.31.56:/d/gicg_dev/')
    ap.add_argument('--root', default=None, help='override local repo root (testing only)')
    ap.add_argument('--dry-run', action='store_true', help='print rsync cmd without executing')
    args = ap.parse_args(argv)
    try:
        root = Path(args.root) if args.root else Path.cwd()
        result = sync(
            direction=args.direction,
            remote=args.remote,
            root=root,
            dry_run=args.dry_run,
        )
    except (ValueError, RuntimeError, SyncConflict) as e:
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
