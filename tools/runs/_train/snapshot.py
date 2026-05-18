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
    """Write cfg_leaf*.toml + cfg_resolved*.toml + metadata.toml(status='running').

    Atomic semantics: all three writes must complete (and metadata be
    valid + flushed) before this function returns. On the fresh path
    any failure midway triggers ``rmtree(state.artifacts_dir)`` so a
    half-populated dir never survives.

    Filename versioning (spec 行 156 pair-versioning):
    - v1 (fresh path, ``state.cfg_resolved_version == 1``) → unsuffixed
      ``cfg_leaf.toml`` + ``cfg_resolved.toml``.
    - vN >= 2 (resume path) → ``cfg_leaf_v<N>.toml`` +
      ``cfg_resolved_v<N>.toml``. Both files always written as a
      paired set (same N) so cfg_leaf history aligns with the
      cfg_resolved truth at each version.

    Resume-path discipline (T-12 fix-up):
    - **Resume path is no-op here.** The vN file writes + metadata bump
      moved into Phase A's allocator-lock critical section (spec 行 155
      requires glob + paired vN write + metadata bump as one atomic
      unit — splitting the write to Phase B post-lock opened a race
      where two parallel resumes both globbed N=2 and overwrote each
      other). Phase B retains the early ``is_resume`` return for the
      lifecycle hook (so dispatch can call Phase B uniformly fresh vs
      resume), but does nothing.

    Fresh-path:
    - Step 4a: ``cfg_leaf.toml`` from ``state.cfg_leaf_bytes`` (pure
      ``write_bytes``; bytes captured in Phase A round-trip exactly).
    - Step 4b: ``cfg_resolved.toml`` via ``dict_to_toml`` +
      ``tomllib.loads`` round-trip-verify (silent emitter bug catch
      at write time, not read time).
    - Step 5: ``metadata.toml`` (status='running') via
      ``write_metadata_atomic``.
    - Failure mid-way → ``rmtree(state.artifacts_dir)`` + re-raise as
      ``SystemExit(2)``. Fresh dir is by definition orphan if Phase B
      fails (no prior artifacts to preserve).

    ``cfg_path`` is the user-passed leaf cfg path (from argv) — used
    by ``_build_initial_metadata`` on the fresh path. Resume path
    ignores this arg (Phase A already wrote it into metadata).
    """
    is_resume = state.cfg_resolved_version > 1
    if is_resume:
        # Phase A already did everything (vN write + metadata bump
        # under allocator lock). Nothing for Phase B to do; returning
        # early avoids both the duplicate-write race and the
        # rmtree-on-failure trap that would destroy a registered dir.
        return

    leaf_name, resolved_name = _versioned_filenames(state.cfg_resolved_version)

    try:
        # Step 4a: leaf snapshot.
        (state.artifacts_dir / leaf_name).write_bytes(state.cfg_leaf_bytes)

        # Step 4b: resolved merged cfg dump.
        resolved_text = dict_to_toml(state.cfg_resolved)
        _verify_round_trip(resolved_text, state.cfg_resolved)
        (state.artifacts_dir / resolved_name).write_text(resolved_text, encoding='utf-8')

        # Step 5: metadata write.
        metadata = _build_initial_metadata(state, cfg_path)
        write_metadata_atomic(state.artifacts_dir, metadata)
    except BaseException as exc:
        # Fresh-path cleanup: orphan dir must not survive.
        try:
            shutil.rmtree(state.artifacts_dir)
        except OSError as cleanup_err:
            print(
                f'tools.runs.train: Phase B orphan-dir cleanup failed for '
                f'{state.artifacts_dir}: {cleanup_err}; manual rmtree required',
                file=sys.stderr,
            )
        if isinstance(exc, SystemExit):
            raise
        print(f'tools.runs.train: Phase B failed: {exc}', file=sys.stderr)
        raise SystemExit(2) from exc


def _versioned_filenames(cfg_resolved_version: int) -> tuple[str, str]:
    """Return ``(leaf_name, resolved_name)`` for the given version.

    Spec 行 156 pair-versioning: v1 is unsuffixed (``cfg_leaf.toml`` /
    ``cfg_resolved.toml``); vN >= 2 is suffixed
    (``cfg_leaf_v<N>.toml`` / ``cfg_resolved_v<N>.toml``). Pure helper
    so test_train_resume.py can pin the naming convention without
    re-deriving it from the suffix logic.
    """
    if cfg_resolved_version < 1:
        raise ValueError(f'cfg_resolved_version must be >= 1, got {cfg_resolved_version}')
    if cfg_resolved_version == 1:
        return ('cfg_leaf.toml', 'cfg_resolved.toml')
    return (f'cfg_leaf_v{cfg_resolved_version}.toml', f'cfg_resolved_v{cfg_resolved_version}.toml')


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
