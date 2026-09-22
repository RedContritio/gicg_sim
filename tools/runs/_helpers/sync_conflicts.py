"""Conflict detection and rsync command construction for ``tools.runs.sync``.

Split out of :mod:`tools.runs.sync` to keep both modules inside the per-file line
limit. ``tools.runs.sync`` re-exports these names, because its tests reach them
through the module object (``from tools.runs import sync`` then ``sync.RSYNC_FLAGS``).

Spec: ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`` (主卷)
+ ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design-rollout.md`` (续卷)
§Cross-host sync / §Conflict / §Case-collide / §Authoritative / §Include-exclude.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.runs._host import RemoteCfg
from tools.runs._helpers.sync_extras import REMOTE_RE_PATTERN


# Hardcoded; user override forbidden (stray ``--exclude=*`` removal could
# leak GB-scale ckpt across a slow link). rsync = first-match-wins.
RSYNC_FLAGS: tuple[str, ...] = (
    '-av',
    '--include=artifacts/',
    '--include=artifacts/*/',
    '--include=artifacts/*/metadata.toml',
    '--include=artifacts/*/cfg_resolved*.toml',
    '--include=artifacts/*/cfg_leaf*.toml',
    '--include=artifacts/*/*/',
    '--include=artifacts/*/*/metadata.toml',
    '--include=artifacts/*/*/cfg_resolved*.toml',
    '--include=artifacts/*/*/cfg_leaf*.toml',
    '--exclude=artifacts/.authoritative_host',
    '--exclude=artifacts/.run_id_lock',
    '--exclude=artifacts/*/.metadata_lock',
    '--exclude=artifacts/*/*/.metadata_lock',
    '--exclude=*',
)

# Strict ``[user@]host:path/`` form; host = hostname / IPv4, or
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


def validate_remote(remote: str) -> None:
    """Strict ``[user@]host:path/`` form. macOS local paths with ``:`` are
    rejected. IPv6 bracket form (``[::1]:/path/``) is accepted
    (spec §HIGH-6-B)."""
    if not _REMOTE_RE.match(remote):
        raise ValueError(
            f'remote {remote!r} must be of form [user@]host:path/ '
            '(host + colon + path + trailing slash; IPv6 bracket form OK)'
        )


def remote_endpoint(remote: RemoteCfg) -> str:
    """Build the rsync endpoint for a validated host registry profile."""
    endpoint = f'{remote.ssh}:{remote.root.rstrip("/")}/'
    validate_remote(endpoint)
    return endpoint


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
    is pre-validated by callers。
    """
    bad = 'remote_newer' if direction == 'push' else 'local_newer'
    excludes: list[str] = []
    for row in rows:
        if row.resolution == bad:
            excludes.extend((f'--exclude=artifacts/*_{row.nnn}_*/', f'--exclude=artifacts/*/*_{row.nnn}/'))
    return excludes


def build_rsync_cmd(
    direction: str,
    remote: RemoteCfg | str,
    *,
    root: Path,
    conflict_rows: list[ConflictRow] | None = None,
) -> list[str]:
    """rsync argv. Conflict ``--exclude`` flags precede include flags
    (first-match-wins). push = local → remote; pull = remote → local."""
    if direction not in ('push', 'pull'):
        raise ValueError(f'direction must be push|pull, got {direction!r}')
    remote_arg = remote_endpoint(remote) if isinstance(remote, RemoteCfg) else remote
    validate_remote(remote_arg)
    local_arg = f'{root}/'  # trailing slash → merge into remote
    extra_excludes = _excludes_for_conflicts(conflict_rows or [], direction=direction)
    # Conflict-exclude FIRST so it matches before any include rule below.
    cmd: list[str] = ['rsync', *extra_excludes, *RSYNC_FLAGS]
    if direction == 'push':
        cmd += [local_arg, remote_arg]
    else:
        cmd += [remote_arg, local_arg]
    return cmd
