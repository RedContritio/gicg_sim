"""``tools.runs.show`` — detail dump of a single run by NNN shorthand.

Clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§CLI show 细则 HIGH-1-C + §Schema CRIT-6-A +
§Malformed metadata 处理 HIGH-4-A.

Behavior:

- Accept any 1-6 digit shorthand (``69`` / ``069`` / ``000069``); internal
  zero-pad to 6 digits + exact match via :func:`resolve_nnn_to_dir`.
- Print every ``metadata.toml`` field (all 11) for human inspection.
- Print **every** ``cfg_resolved*.toml`` (v1 + v2 + ... v<N>) as audit
  trail; the highest-version one is marked ``(current)`` (spec §Resume 语义
  "truth = 最高版").
- Malformed metadata.toml: **raise** (NOT skip like list — show
  targets a single NNN, failing loud is correct per spec §HIGH-4-A).
- Dir-lookup failures (0 / ≥2 match) bubble up from resolver as
  :class:`LookupError`.

CLI::

    .venv/bin/python -m tools.runs.show <NNN>

``<NNN>`` is the 1-6 digit shorthand. Exit codes:

- 0 — success
- 2 — lookup / parse error (LookupError / ValueError / OSError)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from tools.runs import schema
from tools.runs._helpers.resolver import resolve_nnn_to_dir

# Resume-versioned cfg files (spec §Resume 语义): v1 has no suffix,
# v>=2 carries ``_v<N>`` suffix; latest version is current truth.
_CFG_RESOLVED_V_RE = re.compile(r'^cfg_resolved_v(\d+)\.toml$')

# Match list.py's display order; keep in sync with schema._FIELD_ORDER.
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


def _list_cfg_resolved_versions(artifacts_dir: Path) -> list[tuple[int, Path]]:
    """Return sorted ``[(version, path), ...]`` for all ``cfg_resolved*.toml``.

    - ``cfg_resolved.toml`` → version 1 (spec §Resume 语义 "首版固定无后缀").
    - ``cfg_resolved_v<N>.toml`` → version N (N >= 2; spec §Resume 语义).

    Sort ascending by version so the caller can render v1 → v<N> in order.
    Returns ``[]`` when no cfg_resolved files exist (defensive — production
    train.py always writes at least v1, but recover / hand-crafted dirs
    may not).
    """
    versions: list[tuple[int, Path]] = []
    if not artifacts_dir.is_dir():
        return versions
    for entry in artifacts_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.name == 'cfg_resolved.toml':
            versions.append((1, entry))
            continue
        m = _CFG_RESOLVED_V_RE.match(entry.name)
        if m is None:
            continue
        versions.append((int(m.group(1)), entry))
    versions.sort(key=lambda pair: pair[0])
    return versions


def _format_metadata(meta: schema.RunMetadata) -> str:
    """Render all 11 metadata fields as ``key: value`` lines.

    Field order matches :data:`_FIELD_ORDER` (same as ``schema._FIELD_ORDER``
    so the human view tracks the TOML dump order).
    """
    lines = ['=== metadata ===']
    for field in _FIELD_ORDER:
        value = getattr(meta, field)
        lines.append(f'{field}: {value}')
    return '\n'.join(lines)


def show_run(repo_root: Path, nnn: str) -> str:
    """Build the full show-output string for ``nnn`` under ``repo_root``.

    Pure string return (no stdout side effect) so tests can assert on the
    rendered text directly; :func:`main` is the CLI shell that prints it.

    Raises:
        ValueError: ``nnn`` is not a 1-6 digit string (caller bug; resolver
            shape contract).
        LookupError: 0 or ≥2 ``artifacts/`` dirs match the zero-padded NNN
            (spec §HIGH-1-C — show 单 NNN 失败 = 直接 raise).
        OSError / ValueError: malformed ``metadata.toml`` (parse fail / schema
            violation / read error). Per spec §HIGH-4-A, show **does not skip**
            — failing loud on a single-target query is correct.
    """
    artifacts_dir = resolve_nnn_to_dir(repo_root, nnn)
    metadata_path = artifacts_dir / 'metadata.toml'
    # load_file → tomllib.loads → from_dict → validate.
    # Any of these may raise OSError / ValueError; let them propagate
    # per spec §HIGH-4-A (show != list, single-target raise).
    meta = schema.load_file(metadata_path)

    cfg_versions = _list_cfg_resolved_versions(artifacts_dir)
    # current = max version present. Empty list → fall back to metadata's
    # cfg_resolved_version (defensive; both rare hand-crafted dirs and the
    # canonical first-version path stay consistent).
    if cfg_versions:
        current_version = max(v for v, _ in cfg_versions)
    else:
        current_version = meta.cfg_resolved_version

    sections: list[str] = [_format_metadata(meta)]

    if not cfg_versions:
        sections.append('\n=== cfg_resolved ===\n(no cfg_resolved*.toml files in artifacts dir)')
    else:
        for version, path in cfg_versions:
            suffix = ' (current)' if version == current_version else ''
            header = f'\n=== cfg_resolved_v{version}{suffix} ({path.name}) ==='
            body = path.read_text(encoding='utf-8').rstrip('\n')
            sections.append(f'{header}\n{body}')

    return '\n'.join(sections) + '\n'


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        'nnn',
        help='NNN shorthand: 1-6 digit run id (e.g. 69, 069, 000069). Internal zero-pad to 6 digits.',
    )
    # --root undocumented but supported for tests; production runs cwd.
    ap.add_argument('--root', default=None, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.root) if args.root else Path.cwd()
    try:
        output = show_run(repo_root, args.nnn)
    except (LookupError, ValueError, OSError) as e:
        print(f'tools.runs.show: {e}', file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
