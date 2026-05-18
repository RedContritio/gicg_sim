"""tools.runs.helpers — Public API helpers (clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`` §Public
API helper 表 行 533-547).

This module hosts the lock-free helpers (R1-R3): path normalization, raw
cfg checksum (audit only), and leaf-toml meta field extraction. The lock-
ful helpers (R4-R7: NNN allocator, per-run flock context manager, atomic
metadata writer, NNN→dir resolver) are scoped to later tasks (T-03/T-04/
T-05) and intentionally not implemented here.

Stdlib only — no third-party deps. tomllib (Python ≥3.11) handles the TOML
parse. SHA-256 is content-only; mtime/size are intentionally excluded so
identical bytes always produce identical hashes (cross-host audit needs
that).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


def normalize_repo_relative(path: Path, repo_root: Path, label: str) -> str:
    """Return ``path`` as a repo-relative forward-slash POSIX string.

    Resolves both ``path`` and ``repo_root`` to absolute paths (following
    symlinks). Raises ``ValueError`` if the resolved ``path`` does not lie
    under ``repo_root``; the ``label`` is embedded in the error message to
    identify which field rejected the input (e.g. ``'cfg'`` /
    ``'artifacts'``).

    Always returns ``.as_posix()`` form. On Windows this converts
    backslash separators (``configs\\dmc\\x.toml``) to forward slashes
    (``configs/dmc/x.toml``); cross-host metadata sync would otherwise
    fail because POSIX receivers cannot resolve backslash paths.

    Symlink behavior: ``Path.resolve()`` follows symlinks. A repo-internal
    symlink pointing outside the tree is rejected; copy the target into
    the repo if you need it in metadata.
    """
    abs_path = path.resolve()
    abs_root = repo_root.resolve()
    try:
        rel = abs_path.relative_to(abs_root)
    except ValueError as e:
        raise ValueError(
            f'{label} path {str(path)!r} resolves to {str(abs_path)!r} which is outside repo root {str(abs_root)!r}'
        ) from e
    return rel.as_posix()


def cfg_checksum(cfg_path: Path) -> str:
    """Return ``'sha256:<64-hex>'`` of ``cfg_path``'s raw bytes.

    Audit-only — there is no drift guard built on this value (the old
    register/complete pipeline hashed the *merged effective* cfg for
    drift detection; that path is gone). Returns a content-only digest
    so two identical files in different locations hash identically.

    Propagates ``FileNotFoundError`` / ``IsADirectoryError`` / ``OSError``
    from the read — callers should not catch + silently default.
    """
    data = cfg_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return f'sha256:{digest}'


def extract_meta_field(cfg_path: Path, field: str) -> str | None:
    """Return ``cfg.meta.<field>`` from the leaf TOML at ``cfg_path``.

    Does NOT resolve ``meta.extends`` — reads ``cfg_path`` directly and
    inspects only its own ``[meta]`` table (per spec §Public API helper
    表 行 541 "无 extends resolve,纯本地 file 读 leaf toml"). If the leaf
    omits ``[meta]`` or the named field, returns ``None``.

    Strict type contract: if the field is present but not a string, raises
    ``TypeError``. The spec advertises a ``str | None`` return; silently
    coercing non-string values (e.g. ``42`` → ``'42'``) would mask cfg
    bugs.
    """
    data = tomllib.loads(cfg_path.read_text(encoding='utf-8'))
    meta = data.get('meta')
    if not isinstance(meta, dict):
        return None
    value = meta.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f'cfg {cfg_path} meta.{field} expected str, got {type(value).__name__}')
    return value
