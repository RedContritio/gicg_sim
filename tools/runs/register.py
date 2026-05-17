"""``tools.runs.register`` — create a run metadata record (status=pending).

Auto-injects ``git_commit`` (from ``git rev-parse HEAD``, falling back to
``'unknown'``), ``host`` (``socket.gethostname()``), ``cfg_checksum``
(sha256 of cfg file bytes), and ``timestamp`` (iso8601 UTC).

The ``--paradigm`` flag is required only when the cfg TOML does not
contain a top-level ``paradigm`` field (i.e. cfg is malformed or
legacy). On normal cfg, paradigm is auto-extracted.

CLI:

    .venv/bin/python -m tools.runs.register \\
        --run-id r013 --cfg configs/az/runs/r013.toml [--label slug] \\
        [--type r|s] [--paradigm az|bc|cfr|dmc|ppo] [--description '...']

Exits 1 with stderr message on:
- missing cfg file
- cfg missing top-level ``paradigm`` and no ``--paradigm`` override
- run already registered (file exists; rerun would clobber)
- schema validation failure
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import socket
import subprocess
import sys
from pathlib import Path

from tools.runs import schema

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


def _cfg_checksum(cfg_path: Path) -> str:
    """sha256:<hex> of the cfg file bytes."""
    h = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
    return f'sha256:{h}'


def _extract_paradigm(cfg_path: Path) -> str | None:
    """Try to extract top-level ``paradigm`` from a TOML cfg. Return
    None if cfg parses but the field is absent."""
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore
    try:
        data = tomllib.loads(cfg_path.read_text(encoding='utf-8'))
    except Exception as e:
        raise ValueError(f'cfg {cfg_path} is not valid TOML: {e}') from e
    p = data.get('paradigm')
    if p is None:
        return None
    if not isinstance(p, str):
        raise ValueError(f'cfg {cfg_path} top-level paradigm must be a string, got {type(p).__name__}')
    return p


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

    # paradigm: --paradigm override > cfg top-level > error
    extracted = _extract_paradigm(cfg_path)
    chosen_paradigm = paradigm or extracted
    if chosen_paradigm is None:
        raise ValueError(
            f'cfg {cfg_file} has no top-level `paradigm` field; pass --paradigm explicitly (one of az|bc|cfr|dmc|ppo)'
        )

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
        cfg_file=str(cfg_path),
        cfg_checksum=_cfg_checksum(cfg_path),
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
