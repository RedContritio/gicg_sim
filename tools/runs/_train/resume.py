"""tools.runs._train.resume — Phase A resume entry (T-12).

Internal module — callers must use :mod:`tools.runs.train` (the public
entry shell). Implements the spec §Resume 语义 行 145-164 alternative
Phase A path:

- infer ``artifacts_dir`` from ``--resume <ckpt>.parent.parent``
- validate leaf cfg exists + ``<artifacts_dir>/metadata.toml`` exists +
  ``<artifacts_dir>/ckpts/`` is a direct child (CRIT-X-1 sanity guards)
- re-resolve cfg + apply ``--override`` (allow drift)
- allocate ``cfg_resolved_version = N+1`` under the allocator flock so
  two parallel resumes can't collide on N (HIGH-3-A 行 155)
- transition metadata.status to ``running`` via the resume schema
  exception (CRIT-2-A 行 235-246); ``'running' already`` warns + no-op
- preserve metadata.timestamp / metadata.exit_code; H-3 行 185
  ``wall_seconds`` overwrite happens at Phase C close, not here

The version field is bumped HERE (Phase A resume) and propagated to
Phase B via the new :class:`SetupState.cfg_resolved_version` field;
Phase B then suffixes filenames as ``cfg_resolved_v<N>.toml`` /
``cfg_leaf_v<N>.toml`` (spec 行 156 pair-versioning).

Spec cross-refs:
- 行 145-164 §Resume 语义 (full section)
- 行 149     HIGH-2-C 缺 leaf cfg → SystemExit(2)
- 行 153-156 cfg_resolved_v<N> file naming + paired cfg_leaf_v<N>
- 行 155     HIGH-3-A allocator-lock-protected N glob/write
- 行 157-159 CRIT-6-A truth + cfg_resolved_version metadata field
- 行 161     Resume status transition (via validate_transition resume=True)
- 行 162     metadata fields not reset (timestamp/exit_code preserved)
- 行 185     H-3 wall_seconds overwrite (last attempt)
- 行 235-246 CRIT-2-A Resume exception transitions
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from tools.runs import schema
from tools.runs._helpers.locks import _retry_acquire_flock
from tools.runs._helpers.metadata_io import write_metadata_atomic
from tools.runs._helpers.paths import normalize_repo_relative
from tools.runs._train.setup import (
    SetupState,
    _extract_leaf_label,
    _validate_run_label,
    _verify_repo_root,
)
from training.core.config.loader import _apply_overrides, load_with_extends

# Matches cfg_resolved.toml (v1) and cfg_resolved_v<N>.toml (vN, N>=2).
# Anchored to ^ / $ so only the canonical filenames count toward N
# allocation — a stale backup like ``cfg_resolved.toml.bak`` cannot
# bump the version.
_CFG_RESOLVED_V_RE = re.compile(r'^cfg_resolved_v(\d+)\.toml$')


def phase_a_resume(args: argparse.Namespace) -> SetupState:
    """Resume Phase A entry — replaces fresh allocate+mkdir with reuse+revalidate.

    Lifecycle (spec 行 145-164):

    1. Infer ``artifacts_dir = ckpt.parent.parent`` (ckpts/ is a direct
       child of the per-run dir).
    2. Validate ``<cfg>`` exists + is a file (HIGH-2-C 行 149 — no
       "pure ckpt" resume).
    3. Validate ``<artifacts_dir>/metadata.toml`` exists +
       ``<artifacts_dir>/ckpts/`` is a child dir.
    4. Re-resolve cfg via ``load_with_extends`` + apply ``--override``
       (allow drift; spec 行 152).
    5. Re-validate ``run_label`` regex post-resolve (defense in depth
       — leaf cfg might have changed since the original train run).
    6. Allocate ``cfg_resolved_version = max(existing) + 1`` under the
       global allocator flock (spec 行 155 HIGH-3-A — guards parallel
       resume race).
    7. Read current metadata + apply resume status transition via
       :func:`schema.validate_transition` ``resume=True``.
       ``'running' already`` → warn no-op + continue (spec 行 243).
    8. Write updated metadata (status='running', cfg_resolved_version=N,
       cfg_file=new leaf path). ``timestamp`` / ``exit_code`` preserved
       (spec 行 162). ``wall_seconds`` reset to 0.0 — overwritten at
       Phase C close with the last-attempt elapsed (H-3 行 185).

    Returns the :class:`SetupState` for Phase B. Phase B reads
    ``state.cfg_resolved_version`` to suffix filenames.
    """
    _verify_repo_root(Path.cwd())

    ckpt_path = Path(args.resume)
    cfg_path = Path(args.cfg)

    # Step 2 (HIGH-2-C 行 149): leaf cfg must be present + readable.
    # Pinned wording so test_train_resume.py's stderr assertion stays
    # stable across cosmetic edits.
    if not cfg_path.exists() or not cfg_path.is_file():
        print(
            f'tools.runs.train: leaf cfg 缺失,不支持纯 ckpt 续训(必须提供 cfg 才能 resume): {cfg_path}',
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Step 1 + 3: artifacts_dir inference + sanity guards. ckpt path
    # convention is ``<artifacts_dir>/ckpts/ckpt_<n>.pt`` (T-06 layout),
    # so grandparent yields the per-run dir. We do NOT require the ckpt
    # file itself to exist on disk — paradigm may load it lazily inside
    # ``run_pipeline.try_resume`` and we don't want to second-guess that
    # contract here. But the *structure* (metadata.toml present + ckpts/
    # sibling) must hold or we'd silently scribble cfg_resolved_v<N> /
    # metadata bump into a directory that isn't actually a registered run.
    artifacts_dir = ckpt_path.parent.parent
    ckpts_dir = ckpt_path.parent
    metadata_path = artifacts_dir / 'metadata.toml'

    if ckpts_dir.name != 'ckpts' or not ckpts_dir.is_dir():
        print(
            f'tools.runs.train: resume needs registered run; {ckpt_path.parent} 不是合法 artifacts dir '
            f"(expected '<artifacts_dir>/ckpts/ckpt_*.pt')",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not metadata_path.is_file():
        print(
            f'tools.runs.train: resume needs registered run; {ckpt_path.parent} 不是合法 artifacts dir '
            f'(metadata.toml missing at {metadata_path})',
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Step 4: re-resolve cfg + apply --override. Spec 行 152 explicitly
    # allows cfg drift across resume — we re-run the load + override
    # pipeline rather than reading the old cfg_resolved.toml back.
    leaf_bytes = cfg_path.read_bytes()
    leaf_label = _extract_leaf_label(leaf_bytes, cfg_path)
    _validate_run_label(leaf_label, source='leaf cfg.meta.run_label')

    try:
        cfg_resolved = load_with_extends(cfg_path)
    except (ValueError, FileNotFoundError) as e:
        print(f'tools.runs.train: cfg resolve failed: {e}', file=sys.stderr)
        raise SystemExit(2) from e
    if args.override:
        try:
            cfg_resolved = _apply_overrides(cfg_resolved, list(args.override))
        except ValueError as e:
            print(f'tools.runs.train: --override apply failed: {e}', file=sys.stderr)
            raise SystemExit(2) from e

    # Step 5: post-resolve regex re-validate. Cfg drift is allowed; a
    # malformed run_label is not (would break the dir-name convention
    # for any future re-register).
    resolved_meta = cfg_resolved.get('meta')
    resolved_label = resolved_meta.get('run_label') if isinstance(resolved_meta, dict) else None
    _validate_run_label(resolved_label, source='resolved cfg.meta.run_label')

    # Step 6: N allocation under flock. Spec 行 155 mandates
    # ``artifacts/.run_id_lock`` (the global allocator lock). Two
    # parallel resumes against the same dir → first wins, second sees
    # the new vN file on re-glob inside the lock body. Cross-dir
    # resumes serialize too — over-locks but matches spec wording
    # exactly (per HIGH-3-A pinned design).
    repo_root = Path.cwd()
    artifacts_root = repo_root / 'artifacts'
    artifacts_root.mkdir(parents=True, exist_ok=True)
    lock_path = artifacts_root / '.run_id_lock'

    with open(lock_path, 'a+') as fd:
        _retry_acquire_flock(
            fd,
            timeout_msg='unable to acquire run-id lock after 10 retries; check artifacts/.run_id_lock',
        )
        version = _next_cfg_resolved_version(artifacts_dir)
        # Hold the lock through metadata update so a concurrent resume
        # can't sneak a duplicate vN between our glob and the metadata
        # write (the per-dir flock would handle the metadata race but
        # spec 行 155 binds the version to the global allocator lock).
        _bump_metadata_for_resume(
            artifacts_dir=artifacts_dir,
            metadata_path=metadata_path,
            cfg_path=cfg_path,
            cfg_resolved_version=version,
            repo_root=repo_root,
        )

    # Read back the updated metadata for the dir-name timestamp source
    # — resume reuses the original timestamp (spec 行 162 not reset).
    # Re-reading is the natural way to single-source the field that
    # both ``timestamp_utc`` (used downstream) and the on-disk
    # ``metadata.timestamp`` derive from.
    fresh_metadata = schema.load_file(metadata_path)
    timestamp_utc = datetime.fromisoformat(fresh_metadata.timestamp)
    nnn = int(fresh_metadata.run_id)
    label = resolved_label  # type: ignore[assignment]  # validated above to be str

    return SetupState(
        artifacts_dir=artifacts_dir,
        cfg_resolved=cfg_resolved,
        cfg_leaf_bytes=leaf_bytes,
        nnn=nnn,
        label=label,
        timestamp_utc=timestamp_utc,
        cfg_resolved_version=version,
        resume_ckpt_path=ckpt_path,
    )


def _next_cfg_resolved_version(artifacts_dir: Path) -> int:
    """Return the next cfg_resolved version under the per-run dir.

    Algorithm (spec 行 154):
    - If only ``cfg_resolved.toml`` exists (no vN files) → return 2.
    - Else N = max(existing vN) + 1 across all ``cfg_resolved_v<N>.toml``.
    - If neither the base file nor any vN exists → return 2 anyway
      (defensive: a partially-recovered dir where the base file got
      deleted; bumping straight to v2 keeps the audit trail forward-
      only, matching spec line 157 "highest version is truth").

    Called ONLY under the allocator flock — caller must hold it.
    """
    max_version = 1  # v1 is the unsuffixed cfg_resolved.toml
    for entry in artifacts_dir.iterdir():
        if not entry.is_file():
            continue
        m = _CFG_RESOLVED_V_RE.match(entry.name)
        if m is None:
            continue
        n = int(m.group(1))
        if n > max_version:
            max_version = n
    return max_version + 1


def _bump_metadata_for_resume(
    *,
    artifacts_dir: Path,
    metadata_path: Path,
    cfg_path: Path,
    cfg_resolved_version: int,
    repo_root: Path,
) -> None:
    """Read metadata, apply resume status transition, write updated record.

    Called under the allocator flock so the read-modify-write cannot
    interleave with a parallel resume's version glob. The per-run
    metadata lock is re-acquired inside ``write_metadata_atomic`` — on
    POSIX flock cross-fd same-process is generally fine since the
    allocator lock fd is distinct, but the documented warning in
    ``metadata_io.py`` is for cross-fd self-deadlock under Linux's
    BSD-style flock. Here the locks guard different files
    (.run_id_lock vs .metadata_lock), so no self-deadlock.
    """
    current = schema.load_file(metadata_path)

    # Spec 行 243: 'running' already → warn + no-op metadata transition.
    # Still bump cfg_resolved_version + cfg_file (those reflect the
    # resume attempt, not the state machine), but skip the schema-level
    # transition validation that would otherwise be a no-op.
    if current.status == 'running':
        print(
            'tools.runs.train: metadata already running; assuming prev attempt crashed unrecorded, proceeding to resume',
            file=sys.stderr,
        )
    else:
        schema.validate_transition(current.status, 'running', resume=True)

    cfg_file_rel = normalize_repo_relative(cfg_path, repo_root, label='cfg')

    updated = schema.RunMetadata(
        run_id=current.run_id,
        timestamp=current.timestamp,  # spec 行 162 preserved
        cfg_file=cfg_file_rel,
        cfg_resolved_version=cfg_resolved_version,
        git_commit=current.git_commit,  # first-train constant
        host=current.host,
        status='running',
        artifacts_dir=current.artifacts_dir,
        wall_seconds=0.0,  # spec 行 185: overwritten at close
        exit_code=current.exit_code,  # spec 行 162 preserved
        notes=current.notes,
    )
    write_metadata_atomic(artifacts_dir, updated)
