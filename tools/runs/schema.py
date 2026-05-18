"""Run metadata.toml schema (clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``).

11-field dataclass + strict status enum (含 ``unknown`` for recover) +
strict transition table (含 resume 例外 CRIT-2-A).

metadata.toml lives at ``<artifacts_dir>/metadata.toml`` — there is no
longer a separate ``artifacts/runs/<NNN>.toml`` index (spec §Per-run
完全 self-contained). No backward compat with the pre-redesign schema.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

STATUSES: frozenset[str] = frozenset({'running', 'done', 'failed', 'killed', 'unknown'})

# 终态 — mark 拒绝写入 (spec §Status 状态机 行 230)。
# 唯一离开终态的路径是 resume 例外 (spec §Resume 例外规则 CRIT-2-A)。
TERMINAL_STATUSES: frozenset[str] = frozenset({'done', 'failed', 'killed'})

# 6 位 zero-pad NNNNNN (spec §Schema metadata.toml 行 177)
RUN_ID_RE = re.compile(r'^\d{6}$')


class InvalidTransition(ValueError):
    """Raised when :func:`validate_transition` rejects a status change."""


@dataclass
class RunMetadata:
    """Run metadata — exactly 11 fields per spec §Schema metadata.toml 字段.

    Field semantics:
    - ``run_id``: 6-digit zero-padded NNN (e.g. ``"000069"``).
    - ``timestamp``: UTC iso8601, first train start (resume does NOT reset);
      dir-name timestamp is derived from this field.
    - ``cfg_file``: last leaf cfg path used (may not exist; truth is the
      highest-version ``cfg_resolved_v<N>.toml``).
    - ``cfg_resolved_version``: current truth version, first = 1, resume
      increments (round-4 CRIT-6-A).
    - ``git_commit``: full sha or short prefix; ``"unknown"`` if unavailable.
    - ``host``: hostname.
    - ``status``: enum in :data:`STATUSES`; strict transitions enforced by
      :func:`validate_transition`. ``unknown`` = recover-rebuilt state.
    - ``artifacts_dir``: repo-relative path to per-run artifacts dir.
    - ``wall_seconds``: last attempt wall elapsed (resume overwrites);
      ``0.0`` while running.
    - ``exit_code``: train process exit code (spec §Exit codes).
    - ``notes``: free-form string; empty string when absent.
    """

    run_id: str
    timestamp: str
    cfg_file: str
    cfg_resolved_version: int
    git_commit: str
    host: str
    status: str
    artifacts_dir: str
    wall_seconds: float
    exit_code: int
    notes: str


def validate(meta: RunMetadata) -> None:
    """Raise ValueError on any field-level violation. Strict — no silent fix.

    Does NOT validate transitions (use :func:`validate_transition` separately).
    """
    if not isinstance(meta.run_id, str) or not RUN_ID_RE.match(meta.run_id):
        raise ValueError(f'run_id {meta.run_id!r} must match ^\\d{{6}}$ (6-digit zero-pad)')
    if not isinstance(meta.timestamp, str) or not meta.timestamp:
        raise ValueError('timestamp is required (non-empty iso8601 UTC)')
    if not isinstance(meta.cfg_file, str) or not meta.cfg_file:
        raise ValueError('cfg_file is required (non-empty; last leaf path used)')
    if not isinstance(meta.cfg_resolved_version, int) or isinstance(meta.cfg_resolved_version, bool):
        raise ValueError(f'cfg_resolved_version must be int, got {type(meta.cfg_resolved_version).__name__}')
    if meta.cfg_resolved_version < 1:
        raise ValueError(f'cfg_resolved_version {meta.cfg_resolved_version!r} must be >= 1 (first version is 1)')
    if not isinstance(meta.git_commit, str) or not meta.git_commit:
        raise ValueError("git_commit is required (use 'unknown' if unavailable)")
    if not isinstance(meta.host, str) or not meta.host:
        raise ValueError('host is required (non-empty)')
    if meta.status not in STATUSES:
        raise ValueError(f'status {meta.status!r} must be one of {sorted(STATUSES)}')
    if not isinstance(meta.artifacts_dir, str) or not meta.artifacts_dir:
        raise ValueError('artifacts_dir is required (non-empty; repo-relative path)')
    if isinstance(meta.wall_seconds, bool) or not isinstance(meta.wall_seconds, (int, float)):
        raise ValueError(f'wall_seconds must be number, got {type(meta.wall_seconds).__name__}')
    if meta.wall_seconds < 0:
        raise ValueError(f'wall_seconds {meta.wall_seconds!r} must be >= 0')
    if not isinstance(meta.exit_code, int) or isinstance(meta.exit_code, bool):
        raise ValueError(f'exit_code must be int, got {type(meta.exit_code).__name__}')
    if not isinstance(meta.notes, str):
        raise ValueError(f'notes must be str (use empty string when absent), got {type(meta.notes).__name__}')


# Status transition table (spec §Status 状态机 行 226-230 + §Resume 例外规则 行 235-245).
#
# Normal (resume=False): running → {done,failed,killed} (auto by train + manual
# by mark); unknown → {done,failed,killed} (mark, recover 收尾). running →
# running is allowed as the idempotent fresh-start path.
#
# Resume exception (CRIT-2-A): {done,failed,killed,unknown,running} → running.
# running → running under resume is the spec line 243 'already running' no-op
# warn path; schema layer allows it, caller logs the warn.
_NORMAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ('running', 'running'),
        ('running', 'done'),
        ('running', 'failed'),
        ('running', 'killed'),
        ('unknown', 'done'),
        ('unknown', 'failed'),
        ('unknown', 'killed'),
    }
)
_RESUME_EXTRA_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ('done', 'running'),
        ('failed', 'running'),
        ('killed', 'running'),
        ('unknown', 'running'),
        ('running', 'running'),
    }
)


def validate_transition(old: str, new: str, *, resume: bool = False) -> None:
    """Validate a status transition. Raise :class:`InvalidTransition` on violation.

    Per spec §Status 状态机 + §Resume 例外规则:
    - Without ``resume``: only ``running → {done,failed,killed,running}`` and
      ``unknown → {done,failed,killed}`` allowed.
    - With ``resume=True``: also allows
      ``{done,failed,killed,unknown,running} → running`` (CRIT-2-A).
    - Terminal states (done/failed/killed) are otherwise frozen.
    - ``unknown`` is the recover-rebuilt non-terminal state.
    """
    if old not in STATUSES:
        raise ValueError(f'old status {old!r} must be one of {sorted(STATUSES)}')
    if new not in STATUSES:
        raise ValueError(f'new status {new!r} must be one of {sorted(STATUSES)}')
    if (old, new) in _NORMAL_TRANSITIONS:
        return
    if resume and (old, new) in _RESUME_EXTRA_TRANSITIONS:
        return
    if resume:
        raise InvalidTransition(
            f'transition {old!r} → {new!r} not allowed even with resume=True; '
            f'resume only permits {{done,failed,killed,unknown,running}} → running'
        )
    raise InvalidTransition(
        f'transition {old!r} → {new!r} not allowed; '
        f'normal: running → {{done,failed,killed,running}} or unknown → {{done,failed,killed}}; '
        f'{{done,failed,killed}} terminal (use resume=True for resume exception)'
    )


_FIELD_ORDER: tuple[str, ...] = (
    'run_id',
    'timestamp',
    'cfg_file',
    'cfg_resolved_version',
    'git_commit',
    'host',
    'status',
    'artifacts_dir',
    'wall_seconds',
    'exit_code',
    'notes',
)


def _to_plain_dict(meta: RunMetadata) -> dict[str, Any]:
    """Convert to dict suitable for TOML dump (all 11 fields, fixed order)."""
    return {
        'run_id': meta.run_id,
        'timestamp': meta.timestamp,
        'cfg_file': meta.cfg_file,
        'cfg_resolved_version': meta.cfg_resolved_version,
        'git_commit': meta.git_commit,
        'host': meta.host,
        'status': meta.status,
        'artifacts_dir': meta.artifacts_dir,
        'wall_seconds': float(meta.wall_seconds),
        'exit_code': meta.exit_code,
        'notes': meta.notes,
    }


def from_dict(d: dict[str, Any]) -> RunMetadata:
    """Construct + validate RunMetadata from a parsed TOML dict. Strict —
    missing keys raise; unknown keys also raise (stale / corrupt metadata
    must not silently survive)."""
    required = set(_FIELD_ORDER)
    present = set(d.keys())
    missing = sorted(required - present)
    if missing:
        raise ValueError(f'missing required keys: {missing}')
    extra = sorted(present - required)
    if extra:
        raise ValueError(f'unknown keys (stale / corrupt schema?): {extra}')

    raw_wall = d['wall_seconds']
    if isinstance(raw_wall, bool):
        raise ValueError('wall_seconds must be number, got bool')
    if not isinstance(raw_wall, (int, float)):
        raise ValueError(f'wall_seconds must be number, got {type(raw_wall).__name__}')

    meta = RunMetadata(
        run_id=d['run_id'],
        timestamp=d['timestamp'],
        cfg_file=d['cfg_file'],
        cfg_resolved_version=d['cfg_resolved_version'],
        git_commit=d['git_commit'],
        host=d['host'],
        status=d['status'],
        artifacts_dir=d['artifacts_dir'],
        wall_seconds=float(raw_wall),
        exit_code=d['exit_code'],
        notes=d['notes'],
    )
    validate(meta)
    return meta


# Hand-rolled TOML emitter — only supports the flat 11-field shape produced
# by `_to_plain_dict`. No nested tables, no arrays.


def _format_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        s = repr(v)
        if '.' not in s and 'e' not in s and 'n' not in s and 'i' not in s:
            s += '.0'  # force decimal so re-parse gives float
        return s
    if isinstance(v, str):
        escaped = (
            v.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        )
        return f'"{escaped}"'
    raise TypeError(f'unsupported TOML scalar type: {type(v).__name__}')


def dumps(meta: RunMetadata) -> str:
    """Serialize RunMetadata to a TOML string (fixed field order)."""
    validate(meta)
    d = _to_plain_dict(meta)
    return '\n'.join(f'{k} = {_format_scalar(d[k])}' for k in _FIELD_ORDER) + '\n'


def loads(text: str) -> RunMetadata:
    return from_dict(tomllib.loads(text))


def load_file(path: Path) -> RunMetadata:
    """Load + validate. Path is the direct ``<artifacts_dir>/metadata.toml``
    path; no filename-stem invariant (filename is always ``metadata.toml``)."""
    return loads(path.read_text(encoding='utf-8'))


def save_file(meta: RunMetadata, path: Path) -> None:
    """Write metadata to ``path``. Caller handles atomic-rename + per-run
    flock; this helper just writes (used by tests / cold paths)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(meta), encoding='utf-8')
