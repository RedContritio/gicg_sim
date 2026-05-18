"""``tools.runs.recover`` — rebuild ``metadata.toml`` from cfg + ckpts.

Clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§CLI recover 细则 HIGH-4-C 行 137-143 + §Status 状态机 unknown 行 142, 183.

Rescue path for the case where ``<artifacts_dir>/metadata.toml`` is missing
(deletion accident, sync glitch, partial pre-redesign migration) but the
per-run dir + its ``cfg_resolved*.toml`` snapshot are intact. The rebuilt
metadata is written with ``status='unknown'`` — the only status enum value
that ``recover`` may produce, signalling "metadata was synthesised; train
outcome is undetermined" (spec 行 142). The user then transitions to a
terminal state via :mod:`tools.runs.mark` once they confirm what actually
happened (``done`` / ``failed`` / ``killed``).

Design points (per T-16 handoff):

- ``recover`` is a **first-time** metadata write (entry condition is
  metadata.toml missing). Unlike :mod:`tools.runs.mark` /
  :mod:`tools.runs._train.run` (which read-compare-write under an outer
  lock), there is no existing record to compare against, so we delegate
  the atomic write directly to :func:`write_metadata_atomic` — its
  internal per-run flock + temp+rename suffices, no nested-acquire risk.
- ``cfg_resolved_version`` is derived from the **highest-numbered**
  ``cfg_resolved*.toml`` present (spec 行 153-157 truth definition).
  ``cfg_resolved.toml`` (no suffix) is v1; ``cfg_resolved_v<N>.toml`` is vN.
- ``cfg_file`` (last-leaf-path-used) is unknowable from the on-disk state
  — the leaf path lives outside ``artifacts/`` and may have been renamed
  or deleted. We write the sentinel ``'<unknown — recovered>'`` so the
  field is non-empty (schema requires it) and the rescue origin is
  self-documenting in subsequent ``show`` / ``list`` output.
- ``git_commit``: unknowable retroactively (the recover-time HEAD is
  unrelated to the original train-time HEAD). Sentinel ``'unknown'``.
- ``timestamp``: derived from the dir-name 12-digit ``YYYYMMDDHHMM``
  prefix, parsed as UTC and converted to iso8601 — preserves the spec
  invariant that ``metadata.timestamp`` and dir-name ts are same-source
  (spec 行 70). ``wall_seconds`` / ``exit_code`` are unrecoverable, set to
  ``0.0`` / ``0`` per their "absent" semantics.

CLI::

    .venv/bin/python -m tools.runs.recover <artifacts/<ts>_<NNN>_<label>>

Exit codes:

- 0 — metadata rebuilt; ``unknown`` status visible to ``list`` / ``show``
- 2 — invalid dir / missing cfg / metadata already present / IO failure
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.runs import schema
from tools.runs._helpers.metadata_io import write_metadata_atomic
from tools.runs._helpers.paths import normalize_repo_relative


# Dir-name shape per spec §Per-run 行 79 ``<YYYYMMDDHHMM>_<NNNNNN>_<label>``.
# Same regex as ``list._RUN_DIR_RE`` — duplicated here (not imported) because
# the modules sit at the same package layer and a cross-import would create
# an accidental dependency from a rescue-path module to the display module.
_DIR_NAME_RE = re.compile(r'^(\d{12})_(\d{6})_(.+)$')

# Resume-versioned cfg files (spec §Resume 行 153-157). v1 has no suffix;
# v>=2 carries ``_v<N>`` suffix. Same regex as ``list._CFG_RESOLVED_V_RE``
# — duplicated for the same independence reason.
_CFG_RESOLVED_V_RE = re.compile(r'^cfg_resolved_v(\d+)\.toml$')

_CFG_FILE_SENTINEL = '<unknown — recovered>'
_GIT_COMMIT_SENTINEL = 'unknown'
_RECOVER_NOTES = 'recovered via tools.runs.recover'


def _cfg_resolved_version(name: str) -> int:
    """Return version for a ``cfg_resolved*.toml`` filename, 0 if not one.

    ``cfg_resolved.toml`` → 1 (v1, no suffix; spec 行 153).
    ``cfg_resolved_v<N>.toml`` → N (N >= 2; spec 行 155).
    Anything else → 0 (sentinel "not a cfg_resolved snapshot").
    """
    if name == 'cfg_resolved.toml':
        return 1
    m = _CFG_RESOLVED_V_RE.match(name)
    if m is None:
        return 0
    return int(m.group(1))


def _highest_cfg_resolved_version(artifacts_dir: Path) -> int:
    """Scan ``artifacts_dir`` and return the max ``cfg_resolved*.toml`` version.

    Returns 0 if no ``cfg_resolved*.toml`` files exist; caller decides
    whether that's a hard error (recover) or a soft fallback (list).
    """
    best = 0
    for entry in artifacts_dir.iterdir():
        if not entry.is_file():
            continue
        v = _cfg_resolved_version(entry.name)
        if v > best:
            best = v
    return best


def _ts_dir_to_iso(ts_compact: str) -> str:
    """Convert ``YYYYMMDDHHMM`` (12-digit dir prefix) to iso8601 UTC.

    Spec §Per-run 行 70: dir-name ts is UTC minute-truncated; the iso8601
    we write back must be the same instant in the same timezone so a
    future ``register`` -> ``train`` -> ``register`` round-trip on the
    recovered run would reproduce the same dir name.
    """
    if len(ts_compact) != 12 or not ts_compact.isdigit():
        raise ValueError(f'expected 12-digit YYYYMMDDHHMM, got {ts_compact!r}')
    dt = datetime(
        int(ts_compact[0:4]),
        int(ts_compact[4:6]),
        int(ts_compact[6:8]),
        int(ts_compact[8:10]),
        int(ts_compact[10:12]),
        0,
        tzinfo=timezone.utc,
    )
    # ``datetime.isoformat()`` produces ``2026-05-18T03:55:00+00:00``
    # matching the format used by Phase A (``_train/setup.py`` 行 243-244).
    return dt.isoformat()


def _parse_dir_name(name: str) -> tuple[str, str, str]:
    """Split ``<ts>_<NNN>_<label>`` into ``(nnn, label, ts_compact)``.

    Raises ``ValueError`` on shape mismatch — recover refuses to operate
    on dirs that do not match the per-run-dir convention (spec 行 79); we
    cannot synthesise a valid ``run_id`` field without a parseable NNN.
    """
    m = _DIR_NAME_RE.match(name)
    if m is None:
        raise ValueError(
            f'dir name {name!r} does not match <YYYYMMDDHHMM>_<NNNNNN>_<label>; '
            f'cannot derive run_id / timestamp for recover'
        )
    ts_compact, nnn, label = m.group(1), m.group(2), m.group(3)
    return nnn, label, ts_compact


def recover_metadata(repo_root: Path, artifacts_dir: Path) -> schema.RunMetadata:
    """Rebuild ``<artifacts_dir>/metadata.toml`` from on-disk cfg snapshots.

    Per spec §CLI recover 细则 HIGH-4-C 行 137-143:

    1. Validate ``artifacts_dir`` is an existing directory under
       ``repo_root/artifacts/``.
    2. **Refuse to overwrite** an existing ``metadata.toml`` — recover is
       the rebuild-from-loss path, not a re-sync command. User must
       explicitly ``rm metadata.toml`` if they really want to re-run
       recovery (spec 行 139 "metadata.toml 缺失但 dir 在 的救援路径").
    3. Require at least one ``cfg_resolved*.toml`` snapshot present —
       without it we have no anchor for ``cfg_resolved_version`` and no
       way to derive paradigm via ``list._derive_paradigm``. Raise
       ``FileNotFoundError`` if absent.
    4. Parse the dir-name into ``(nnn, label, ts_compact)``; convert
       ``ts_compact`` to iso8601 UTC for the ``timestamp`` field
       (preserving the spec 行 70 "single source" invariant for any
       subsequent operation that re-derives the dir name).
    5. Construct an 11-field :class:`schema.RunMetadata` with:

       - ``status='unknown'`` (spec 行 142 — recover is the **only** writer
         of this enum value)
       - ``cfg_file`` / ``git_commit`` set to sentinel strings (the schema
         requires non-empty; we cannot fabricate plausible values)
       - ``wall_seconds=0.0`` / ``exit_code=0`` (unrecoverable; matches
         their "absent" defaults from Phase B init)
       - ``notes='recovered via tools.runs.recover'`` (audit trail for
         downstream ``mark`` / ``show``)

    6. Delegate the write to :func:`write_metadata_atomic` — its internal
       per-run flock + ``os.replace`` give us atomicity for free, and
       there's no existing record to compare against (so no
       read-compare-write outer-lock pattern needed).

    Args:
        repo_root: Repo root (production: ``Path.cwd()``).
        artifacts_dir: Per-run dir under ``repo_root/artifacts/``.

    Returns:
        The freshly-written :class:`schema.RunMetadata` (so callers / tests
        can assert on its fields without re-reading the file).

    Raises:
        ValueError: ``artifacts_dir`` is not a directory, or its name does
            not match the per-run-dir regex, or its resolved path lies
            outside ``repo_root``.
        FileExistsError: ``<artifacts_dir>/metadata.toml`` already exists
            (refuse to clobber — user must rm it explicitly).
        FileNotFoundError: no ``cfg_resolved*.toml`` snapshot in
            ``artifacts_dir``; recover cannot synthesise version.
        OSError: filesystem IO failure during atomic write.
    """
    if not artifacts_dir.is_dir():
        raise ValueError(f'not a directory: {artifacts_dir}')

    metadata_path = artifacts_dir / 'metadata.toml'
    if metadata_path.exists():
        raise FileExistsError(
            f'metadata.toml already exists at {artifacts_dir}; '
            f'recover only rebuilds missing metadata. To re-run recovery, '
            f'rm the existing file explicitly.'
        )

    highest_version = _highest_cfg_resolved_version(artifacts_dir)
    if highest_version == 0:
        raise FileNotFoundError(
            f'no cfg_resolved*.toml found in {artifacts_dir}; cannot recover '
            f'(cfg snapshot is the only anchor for cfg_resolved_version)'
        )

    nnn, _label, ts_compact = _parse_dir_name(artifacts_dir.name)
    timestamp_utc = _ts_dir_to_iso(ts_compact)

    # ``normalize_repo_relative`` enforces that ``artifacts_dir`` resolves
    # under ``repo_root`` — guards against recovering a dir that lives on
    # a different volume / outside the tree, which would write a metadata
    # whose ``artifacts_dir`` field cross-host sync cannot resolve.
    artifacts_dir_rel = normalize_repo_relative(artifacts_dir, repo_root, 'artifacts_dir')

    metadata = schema.RunMetadata(
        run_id=nnn,
        timestamp=timestamp_utc,
        cfg_file=_CFG_FILE_SENTINEL,
        cfg_resolved_version=highest_version,
        git_commit=_GIT_COMMIT_SENTINEL,
        host=socket.gethostname(),
        status='unknown',
        artifacts_dir=artifacts_dir_rel,
        wall_seconds=0.0,
        exit_code=0,
        notes=_RECOVER_NOTES,
    )

    # First-time write — no read-compare-write outer lock needed; helper
    # acquires the per-run flock + atomic temp+rename internally.
    write_metadata_atomic(artifacts_dir, metadata)
    return metadata


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        'dir',
        type=Path,
        help='artifacts/<ts>_<NNN>_<label>/ directory to recover '
        '(metadata.toml must be absent; cfg_resolved*.toml must be present)',
    )
    # --root undocumented but supported for tests; production runs cwd.
    ap.add_argument('--root', default=None, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.root) if args.root else Path.cwd()
    try:
        meta = recover_metadata(repo_root, args.dir)
    except (FileNotFoundError, FileExistsError, ValueError, OSError) as e:
        print(f'tools.runs.recover: {e}', file=sys.stderr)
        return 2
    print(
        f'recovered metadata: nnn={meta.run_id} status={meta.status} cfg_resolved_version={meta.cfg_resolved_version}',
        file=sys.stderr,
    )
    print(
        f'next: tools.runs.mark {meta.run_id} --status killed/done/failed --notes "..."',
        file=sys.stderr,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
