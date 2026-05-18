"""tools.runs._train.snapshot — Phase B lifecycle (steps 4-5).

Internal module — callers must use :mod:`tools.runs.train` (the public
entry shell). Implements lifecycle steps 4 and 5:

- step 4a  write ``cfg_leaf.toml`` from ``state.cfg_leaf_bytes`` (immutable
          snapshot of user's leaf cfg, captured in Phase A step 1)
- step 4b  write ``cfg_resolved.toml`` from ``state.cfg_resolved`` (post
          extends + post --override merged dict, the reproducibility truth)
- step 5  write ``metadata.toml`` (status='running') via
          ``write_metadata_atomic`` (per-run flock + temp + rename)

The hand-rolled TOML emitter used by step 4b lives in
:mod:`tools.runs._train.cfg_toml` (split out per the 300-line file
budget).

Failure handling (spec 行 51, 53, 301):

- Any IO / serialization error → ``rmtree(state.artifacts_dir)`` then
  re-raise as ``SystemExit(2)``. The mkdir in Phase A step 3 created the
  per-run dir; if we cannot complete the cfg+metadata writes the dir
  must not survive as a half-finished orphan that ``list`` / ``show``
  would otherwise have to skip.
- If the rmtree itself fails, an informational warning goes to stderr
  but the original IO exception still drives the SystemExit (cleanup
  diagnostics never mask the root cause; CLAUDE.md §2 + spec 行 301
  finally-block discipline).

Spec cross-refs (``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``):

- 行 50-53  Architecture step 4-5 + orphan-dir rmtree
- 行 76-96  Per-run dir layout (cfg_leaf / cfg_resolved / metadata)
- 行 82     Even when cfg has no extends, cfg_leaf and cfg_resolved
            both get written (structural symmetry)
- 行 174-189 Schema metadata.toml 11 fields
- 行 279-292 Per-run metadata_lock + atomic rename
- 行 301     finally try/except discipline (cleanup never masks root)
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from pathlib import Path

from tools.runs import schema
from tools.runs._helpers.metadata_io import write_metadata_atomic
from tools.runs._helpers.paths import normalize_repo_relative
from tools.runs._train.cfg_toml import dict_to_toml
from tools.runs._train.setup import SetupState


def phase_b_write_cfg_metadata(state: SetupState, cfg_path: Path) -> None:
    """Write cfg_leaf.toml + cfg_resolved.toml + metadata.toml(status='running').

    Atomic semantics: all three files must exist (and metadata must be
    valid + flushed) before this function returns. Any failure midway
    triggers ``rmtree(state.artifacts_dir)`` so a half-populated dir
    never survives.

    The leaf-bytes write is a pure ``write_bytes`` (no re-encoding —
    bytes captured in Phase A round-trip exactly). The resolved-dict
    write goes through ``dict_to_toml`` then immediate
    ``tomllib.loads`` round-trip-verify so a silent emitter bug cannot
    let a non-parseable cfg_resolved sneak past. Metadata write is
    routed through the existing ``write_metadata_atomic`` helper (per-
    run flock + temp + rename).

    ``cfg_path`` is the user-passed leaf cfg path (from argv) — recorded
    in ``metadata.cfg_file`` as the "last leaf path used" per spec 行
    179. Plumbed as an explicit arg rather than on SetupState so the
    Phase A dataclass shape stays exactly the 6 documented fields.
    """
    try:
        # Step 4a: immutable leaf snapshot (bytes, no re-encoding).
        leaf_target = state.artifacts_dir / 'cfg_leaf.toml'
        leaf_target.write_bytes(state.cfg_leaf_bytes)

        # Step 4b: resolved merged cfg dump.
        resolved_text = dict_to_toml(state.cfg_resolved)
        # Round-trip verify: a silent emitter bug would otherwise let a
        # non-parseable cfg_resolved.toml sneak past, breaking later
        # tooling (show / list / resume) that reads this file.
        _verify_round_trip(resolved_text, state.cfg_resolved)
        resolved_target = state.artifacts_dir / 'cfg_resolved.toml'
        resolved_target.write_text(resolved_text, encoding='utf-8')

        # Step 5: initial metadata.toml (status='running').
        metadata = _build_initial_metadata(state, cfg_path)
        write_metadata_atomic(state.artifacts_dir, metadata)
    except BaseException as exc:
        # Spec 行 51, 53: orphan-dir rmtree on Phase B failure. Spec 行
        # 301: cleanup errors never mask the root cause — log and let
        # the original raise propagate.
        try:
            shutil.rmtree(state.artifacts_dir)
        except OSError as cleanup_err:
            print(
                f'tools.runs.train: Phase B orphan-dir cleanup failed for '
                f'{state.artifacts_dir}: {cleanup_err}; manual rmtree required',
                file=sys.stderr,
            )
        # If the original was already a SystemExit propagate as-is; else
        # wrap in SystemExit(2) per CLI exit-code convention (spec
        # §Exit codes — cfg / setup error = 2).
        if isinstance(exc, SystemExit):
            raise
        print(f'tools.runs.train: Phase B failed: {exc}', file=sys.stderr)
        raise SystemExit(2) from exc


def _build_initial_metadata(state: SetupState, cfg_path: Path) -> schema.RunMetadata:
    """Construct the initial ``running``-state RunMetadata for a fresh run.

    Spec §Schema (行 174-189) — 11 fields. ``wall_seconds=0.0`` and
    ``exit_code=0`` are placeholders during 'running'; Phase C (T-10)
    overwrites both at close. ``cfg_file`` is the **leaf** cfg path
    that the user originally passed (spec 行 179: "last leaf path
    used"); the snapshotted bytes live in ``cfg_leaf.toml`` under the
    per-run dir for reproducibility (the snapshot is the truth — spec
    caveats the recorded path "可能不存在/已改").

    ``cfg_resolved_version=1`` since this is fresh train (spec 行 180:
    "首版 = 1, resume 递增"; T-12 handles resume increment).

    ``git_commit`` via ``git rev-parse HEAD`` subprocess; falls back to
    ``'unknown'`` if git is missing or the repo is bare (CI / detached
    envs). Spec §Schema only requires a non-empty string and reserves
    the literal ``'unknown'`` as the documented fallback.
    """
    repo_root = Path.cwd()
    cfg_file_rel = normalize_repo_relative(cfg_path, repo_root, label='cfg')
    artifacts_dir_rel = normalize_repo_relative(state.artifacts_dir, repo_root, label='artifacts')
    return schema.RunMetadata(
        run_id=f'{state.nnn:06d}',
        timestamp=state.timestamp_utc.isoformat(),
        cfg_file=cfg_file_rel,
        cfg_resolved_version=1,
        git_commit=_git_commit_or_unknown(repo_root),
        host=socket.gethostname(),
        status='running',
        artifacts_dir=artifacts_dir_rel,
        wall_seconds=0.0,
        exit_code=0,
        notes='',
    )


def _git_commit_or_unknown(repo_root: Path) -> str:
    """Return current HEAD sha, or ``'unknown'`` if git is unavailable.

    Uses ``subprocess.run`` with timeout (defensive against hung git
    processes in pathological repos). Spec §Schema only requires the
    field be a non-empty string; ``'unknown'`` is the documented
    fallback for CI / detached / no-git environments.
    """
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    if result.returncode != 0:
        return 'unknown'
    sha = result.stdout.strip()
    return sha if sha else 'unknown'


def _verify_round_trip(emitted_text: str, expected: dict) -> None:
    """Parse the emitted TOML and assert equality with the source dict.

    Defensive — emitter bugs (missing escape, lost type, wrong section
    order) would otherwise produce a cfg_resolved.toml that fails to
    parse or parses to a different shape than what Phase B promised.
    Catching this at write time gives a localized error; catching it
    at read time (in show / resume) gives an oblique one.
    """
    try:
        import tomllib
    except ImportError:  # pragma: no cover — Python <3.11 fallback
        import tomli as tomllib  # type: ignore
    try:
        reparsed = tomllib.loads(emitted_text)
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f'cfg_resolved.toml emit produced non-parseable TOML: {e}') from e
    if reparsed != expected:
        raise RuntimeError(
            'cfg_resolved.toml emit round-trip mismatch — emitted TOML re-parses '
            'to a different dict than the source state.cfg_resolved'
        )
