"""``tools.runs.register`` — create a run metadata record (status=pending).

Auto-injects ``git_commit`` (from ``git rev-parse HEAD``, falling back
to ``'unknown'``), ``host`` (``socket.gethostname()``), ``cfg_checksum``
(sha256 of the *merged effective* cfg post ``meta.extends`` resolution
— canonical JSON form, see ``_cfg_checksum``), and ``timestamp``
(iso8601 UTC).

``--paradigm`` and ``cfg.meta.run_label`` are required:
- ``meta.paradigm`` auto-extracted from cfg; ``--paradigm`` is the CLI
  override / fallback when [meta] table or its paradigm field is absent.
- ``meta.run_label`` MUST be present in the cfg (used as the artifacts
  dir suffix by ``CheckpointManager.init_artifacts_dir``). Snapshot
  stored in ``RunMetadata.cfg_run_label`` so post-train ``show`` /
  ``sync`` can reconstruct the dir name.

``cfg_file`` is stored repo-relative (cross-host portability); paths
outside the repo root are rejected.

CLI:

    .venv/bin/python -m tools.runs.register \\
        --run-id r013 --cfg configs/az/runs/r013.toml [--label slug] \\
        [--type r|s] [--paradigm az|bc|cfr|dmc|ppo] [--description '...']

Exits 1 with stderr message on:
- missing cfg file
- cfg missing ``meta.paradigm`` and no ``--paradigm`` override
- cfg missing ``meta.run_label``
- cfg_file path outside repo root
- run already registered (file exists; rerun would clobber)
- schema validation failure
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

from tools.runs import schema
from training.core.config.loader import _load_with_extends

_LABEL_NNN_RE = re.compile(r'^([rs])(\d{3})_')


def _git_commit() -> str:
    """Return current git HEAD hash, or 'unknown' on any failure."""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip() or 'unknown'
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return 'unknown'


def _resolve_cfg(cfg_path: Path) -> dict:
    """Resolve cfg's ``meta.extends`` chain via the canonical loader.
    Raises ValueError on malformed TOML; FileNotFoundError propagates
    when an extends target is missing (caller intent: surface broken
    inheritance, don't silently fall back to leaf-only)."""
    try:
        return _load_with_extends(cfg_path)
    except FileNotFoundError:
        raise
    except Exception as e:
        raise ValueError(f'cfg {cfg_path} is not valid TOML or extends chain broken: {e}') from e


def _cfg_checksum(cfg_path: Path) -> str:
    """sha256:<hex> of the merged effective cfg post extends-chain
    resolution, serialized as canonical JSON (sort_keys=True). Two leaf
    cfgs with identical text but different parents produce different
    checksums — leaf-only hashing would defeat reproducibility-pin."""
    merged = _resolve_cfg(cfg_path)
    canonical = json.dumps(merged, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    h = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return f'sha256:{h}'


def _extract_meta_field(cfg_path: Path, field_name: str) -> str | None:
    """Extract ``meta.<field_name>`` (string) from a resolved cfg.
    Returns None if [meta] table or the field is absent; raises
    ValueError if the field is present but not a string."""
    merged = _resolve_cfg(cfg_path)
    meta = merged.get('meta')
    if not isinstance(meta, dict):
        return None
    v = meta.get(field_name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError(f'cfg {cfg_path} meta.{field_name} must be a string, got {type(v).__name__}')
    return v


def _extract_paradigm(cfg_path: Path) -> str | None:
    return _extract_meta_field(cfg_path, 'paradigm')


def _extract_run_label(cfg_path: Path) -> str | None:
    return _extract_meta_field(cfg_path, 'run_label')


def _normalize_repo_relative(p: Path, repo_root: Path, *, label: str = 'path') -> str:
    """Return repo-relative path string. Reject paths outside repo root
    (cross-host metadata sync needs portable references; absolute paths
    on dev machine are meaningless on the receiver). ``label`` appears
    in the error message (e.g. 'cfg_file', 'artifacts_dir')."""
    abs_p = p.resolve()
    abs_repo = repo_root.resolve()
    try:
        rel = abs_p.relative_to(abs_repo)
    except ValueError as e:
        raise ValueError(
            f'{label} {p} resolves to {abs_p} which is outside repo root {abs_repo}; '
            f'pass a repo-relative path or run from repo root'
        ) from e
    return str(rel)


def _infer_label(run_id: str) -> str:
    """Default label is the run_id itself; caller may override via --label."""
    return run_id


def _infer_type_from_run_id(run_id: str) -> str:
    m = schema.RUN_ID_RE.match(run_id)
    if not m:
        raise ValueError(f'run_id {run_id!r} must match <r|s><NNN>')
    return m.group(1)


def register(
    *,
    run_id: str,
    cfg_file: str,
    label: str | None = None,
    type_: str | None = None,
    paradigm: str | None = None,
    description: str = '',
    root: Path | None = None,
    now: datetime.datetime | None = None,
    host: str | None = None,
    git_commit: str | None = None,
) -> schema.RunMetadata:
    """Programmatic entry point used by both the CLI and tests.

    ``root`` lets tests redirect the on-disk runs dir to a tmp path
    without monkeypatching cwd. ``now`` / ``host`` / ``git_commit`` are
    injectable for deterministic tests.
    """
    cfg_path = Path(cfg_file)
    if not cfg_path.exists():
        raise FileNotFoundError(f'cfg file not found: {cfg_file}')

    # paradigm: --paradigm override > cfg meta.paradigm > error
    extracted = _extract_paradigm(cfg_path)
    chosen_paradigm = paradigm or extracted
    if chosen_paradigm is None:
        raise ValueError(
            f'cfg {cfg_file} has no `meta.paradigm` field; pass --paradigm explicitly (one of az|bc|cfr|dmc|ppo)'
        )

    # cfg.meta.run_label is required — snapshotted into metadata so
    # post-train `show` / `sync` can reconstruct the artifacts dir.
    cfg_run_label = _extract_run_label(cfg_path)
    if not cfg_run_label:
        raise ValueError(
            f'cfg {cfg_file} has no `meta.run_label` field; required (artifacts dir suffix per CheckpointManager)'
        )

    # cfg_file: normalize to repo-relative; `root` doubles as repo_root
    # in tests (cfg lives under tmp_path), defaults to cwd in production
    # (per CLAUDE.md "All commands run from repo root").
    repo_root = root if root is not None else Path.cwd()
    cfg_file_rel = _normalize_repo_relative(cfg_path, repo_root, label='cfg_file')

    inferred_type = _infer_type_from_run_id(run_id)
    chosen_type = type_ or inferred_type
    if chosen_type != inferred_type:
        raise ValueError(f'--type {chosen_type!r} contradicts run_id {run_id!r} prefix {inferred_type!r}')

    chosen_label = label or _infer_label(run_id)
    # Soft sanity: if label has <type><NNN>_ prefix, must match run_id.
    lm = _LABEL_NNN_RE.match(chosen_label)
    if lm and (lm.group(1) != chosen_type or lm.group(2) != run_id[1:]):
        raise ValueError(
            f'label {chosen_label!r} embeds id {lm.group(1)}{lm.group(2)} which contradicts run_id {run_id!r}'
        )

    ts = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    host_name = host or socket.gethostname() or 'unknown'
    commit = git_commit if git_commit is not None else _git_commit()

    meta = schema.RunMetadata(
        run_id=run_id,
        label=chosen_label,
        type=chosen_type,
        timestamp=ts,
        paradigm=chosen_paradigm,
        cfg_file=cfg_file_rel,
        cfg_checksum=_cfg_checksum(cfg_path),
        cfg_run_label=cfg_run_label,
        git_commit=commit,
        host=host_name,
        status='pending',
        summary=schema.Summary(description=description),
    )
    schema.validate(meta)

    out_path = schema.run_path(run_id, root=root)
    if out_path.exists():
        raise FileExistsError(
            f'run {run_id} already registered at {out_path}; use a fresh run_id or delete the file manually'
        )
    schema.save_file(meta, out_path)
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-id', required=True, help='r013 / s069 (matches <r|s><NNN>)')
    ap.add_argument('--cfg', required=True, dest='cfg_file', help='path to cfg TOML (repo-relative)')
    ap.add_argument('--label', default=None, help='slug label; defaults to run_id')
    ap.add_argument('--type', default=None, dest='type_', choices=['r', 's'])
    ap.add_argument('--paradigm', default=None, choices=sorted(schema.PARADIGMS))
    ap.add_argument('--description', default='', help='free-form description')
    ap.add_argument('--root', default=None, help='override repo root (testing only)')
    args = ap.parse_args(argv)
    try:
        meta = register(
            run_id=args.run_id,
            cfg_file=args.cfg_file,
            label=args.label,
            type_=args.type_,
            paradigm=args.paradigm,
            description=args.description,
            root=Path(args.root) if args.root else None,
        )
    except (ValueError, FileNotFoundError, FileExistsError) as e:
        print(f'tools.runs.register: {e}', file=sys.stderr)
        return 1
    print(meta.run_id)
    return 0


if __name__ == '__main__':
    sys.exit(main())
