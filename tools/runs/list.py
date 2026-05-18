"""``tools.runs.list`` — table view scanning ``artifacts/*/metadata.toml``.

Clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§CLI list 细则 HIGH-1-B 行 112-118 + §错误处理 Malformed metadata
HIGH-4-A 行 315-321.

Behavior:

- Scan ``<repo>/artifacts/`` direct children; for each dir matching
  ``^\\d{12}_(\\d{6})_<label>`` read ``<dir>/metadata.toml``.
- ``--status`` / ``--paradigm`` filter (post-load).
- ``paradigm`` derived live from the **highest-version**
  ``cfg_resolved*.toml`` ``meta.paradigm`` (spec line 116 + line 157).
- Default sort: ``timestamp desc`` (newest first; spec line 114).
- Malformed metadata: stderr warn ``'skipping <NNN>: malformed
  metadata'`` + skip (spec line 318 "不让一坏全坏").
- Output: ``NNN | status | paradigm | started | wall | run_label |
  notes`` (spec line 117).

CLI::

    .venv/bin/python -m tools.runs.list [--status <s>] [--paradigm <p>]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.runs import schema
from tools.runs._helpers.paths import extract_meta_field

# Dir-name shape per spec §Per-run 行 79 ``<YYYYMMDDHHMM>_<NNNNNN>_<label>``.
# ``^`` + ``\d{12}`` prefix guard skips pre-redesign legacy dirs
# (``r001_old/``, ``pre_redesign_xxx/``) and the ``.run_id_lock`` file.
_RUN_DIR_RE = re.compile(r'^\d{12}_(\d{6})_(.+)$')

# Resume-versioned cfg files (spec §Resume 行 153-157): v1 has no suffix,
# v>=2 carries ``_v<N>`` suffix; latest version is current truth.
_CFG_RESOLVED_V_RE = re.compile(r'^cfg_resolved_v(\d+)\.toml$')

# Must stay in sync with schema.STATUSES and the 5 paradigm slugs.
_STATUS_CHOICES = ('running', 'done', 'failed', 'killed', 'unknown')
_PARADIGM_CHOICES = ('az', 'bc', 'cfr', 'dmc', 'ppo')


@dataclass(frozen=True)
class _Row:
    """One scanned run with the 7 display columns pre-extracted."""

    nnn: str
    status: str
    paradigm: str
    timestamp: str  # raw iso8601 (sort key); ``_short_date`` for display
    wall_seconds: float
    run_label: str
    notes: str


def _cfg_resolved_version(name: str) -> int:
    """Return version number for a cfg_resolved filename, or 0 if not one.

    ``cfg_resolved.toml`` → 1 (v1, no suffix; spec line 153).
    ``cfg_resolved_v<N>.toml`` → N (N >= 2; spec line 155).
    """
    if name == 'cfg_resolved.toml':
        return 1
    m = _CFG_RESOLVED_V_RE.match(name)
    if m is None:
        return 0
    return int(m.group(1))


def _derive_paradigm(run_dir: Path) -> str:
    """Read ``cfg.meta.paradigm`` from the highest-version cfg_resolved.

    Spec line 116 + line 157: 实时读最高版 cfg_resolved 的 meta.paradigm.
    Returns ``'?'`` on missing file, parse error, or absent field —
    paradigm is display-only, metadata.toml validate is the gating check.
    """
    best_version = 0
    best_path: Path | None = None
    for entry in run_dir.iterdir():
        if not entry.is_file():
            continue
        v = _cfg_resolved_version(entry.name)
        if v > best_version:
            best_version = v
            best_path = entry
    if best_path is None:
        return '?'
    try:
        value = extract_meta_field(best_path, 'paradigm')
    except (OSError, ValueError, TypeError):
        return '?'
    if value is None:
        return '?'
    return value


def _scan_one(run_dir: Path) -> _Row | None:
    """Load + validate one ``<run_dir>/metadata.toml``, return a ``_Row``.

    Malformed metadata (parse fail / schema fail / read error) → stderr
    warn ``'skipping <NNN>: malformed metadata (<reason>)'`` + return
    ``None`` (spec line 318: 不让一坏全坏). Missing metadata.toml is
    silent-skip (recover-eligible state, not corruption).
    """
    metadata_path = run_dir / 'metadata.toml'
    m = _RUN_DIR_RE.match(run_dir.name)
    nnn_from_dir = m.group(1) if m else '?'
    label_from_dir = m.group(2) if m else run_dir.name

    if not metadata_path.is_file():
        return None

    try:
        meta = schema.load_file(metadata_path)
    except (OSError, ValueError) as e:
        # tomllib.TOMLDecodeError IS a ValueError subclass; schema
        # validate raises plain ValueError; OSError covers read failures.
        print(f'skipping {nnn_from_dir}: malformed metadata ({e})', file=sys.stderr)
        return None

    return _Row(
        nnn=meta.run_id,
        status=meta.status,
        paradigm=_derive_paradigm(run_dir),
        timestamp=meta.timestamp,
        wall_seconds=meta.wall_seconds,
        run_label=label_from_dir,
        notes=meta.notes,
    )


def list_runs(
    repo_root: Path,
    *,
    status_filter: str | None = None,
    paradigm_filter: str | None = None,
) -> list[_Row]:
    """Scan ``repo_root/artifacts/`` and return rows sorted timestamp desc.

    Empty/missing ``artifacts/`` → ``[]``. Malformed metadata → skip +
    stderr warn (spec HIGH-4-A). Tie-break by ``nnn`` desc for
    deterministic output.
    """
    if status_filter is not None and status_filter not in _STATUS_CHOICES:
        raise ValueError(f'status_filter {status_filter!r} must be one of {_STATUS_CHOICES}')
    if paradigm_filter is not None and paradigm_filter not in _PARADIGM_CHOICES:
        raise ValueError(f'paradigm_filter {paradigm_filter!r} must be one of {_PARADIGM_CHOICES}')

    artifacts_dir = repo_root / 'artifacts'
    if not artifacts_dir.is_dir():
        return []

    rows: list[_Row] = []
    for entry in artifacts_dir.iterdir():
        if not entry.is_dir():
            continue
        if _RUN_DIR_RE.match(entry.name) is None:
            continue
        row = _scan_one(entry)
        if row is None:
            continue
        if status_filter is not None and row.status != status_filter:
            continue
        if paradigm_filter is not None and row.paradigm != paradigm_filter:
            continue
        rows.append(row)

    rows.sort(key=lambda r: (r.timestamp, r.nnn), reverse=True)
    return rows


def _short_date(ts: str) -> str:
    """Strip iso8601 to its date prefix (chars before ``T``)."""
    if 'T' in ts:
        return ts.split('T', 1)[0]
    return ts[:10]


def _format_wall(seconds: float) -> str:
    """Human-readable duration: ``-`` / ``<n>s`` / ``<m>m<s>s`` / ``<h>h<m>m``."""
    if seconds <= 0:
        return '-'
    total = int(seconds)
    if total < 60:
        return f'{total}s'
    if total < 3600:
        return f'{total // 60}m{total % 60}s'
    return f'{total // 3600}h{(total % 3600) // 60}m'


def render_table(rows: list[_Row]) -> str:
    """Render rows as a fixed-width table (stdlib only).

    Columns (spec line 117):
    ``NNN | status | paradigm | started | wall | run_label | notes``.
    ``notes`` truncated to first line + 60-char limit with ``…`` suffix.
    """
    headers = ('NNN', 'status', 'paradigm', 'started', 'wall', 'run_label', 'notes')
    body: list[tuple[str, ...]] = []
    for r in rows:
        notes = r.notes.replace('\r', ' ').split('\n', 1)[0]
        if len(notes) > 60:
            notes = notes[:59] + '…'
        body.append(
            (
                r.nnn,
                r.status,
                r.paradigm,
                _short_date(r.timestamp),
                _format_wall(r.wall_seconds),
                r.run_label,
                notes,
            )
        )

    widths = [len(h) for h in headers]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(row: tuple[str, ...]) -> str:
        return '  '.join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()

    lines = [fmt(headers), fmt(tuple('-' * w for w in widths))]
    for row in body:
        lines.append(fmt(row))
    return '\n'.join(lines) + '\n'


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        '--status',
        default=None,
        choices=_STATUS_CHOICES,
        help='filter by status enum (default: show all)',
    )
    ap.add_argument(
        '--paradigm',
        default=None,
        choices=_PARADIGM_CHOICES,
        help='filter by paradigm (read live from cfg_resolved.meta.paradigm)',
    )
    # --root undocumented but supported for tests; production runs cwd.
    ap.add_argument('--root', default=None, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.root) if args.root else Path.cwd()
    rows = list_runs(repo_root, status_filter=args.status, paradigm_filter=args.paradigm)
    if not rows:
        artifacts_dir = repo_root / 'artifacts'
        print(f'(no runs found under {artifacts_dir}; start one with `tools.runs.train <cfg>`)')
        return 0
    sys.stdout.write(render_table(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
