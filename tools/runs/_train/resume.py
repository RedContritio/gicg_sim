"""tools.runs._train.resume — Phase A resume entry (T-12).

Internal module — callers must use :mod:`tools.runs.train` (the public
entry shell). Implements the spec §Resume 语义 alternative
Phase A path:

- infer ``artifacts_dir`` from ``--resume <ckpt>.parent.parent``
- validate leaf cfg exists + ``<artifacts_dir>/metadata.toml`` exists +
  ``<artifacts_dir>/ckpts/`` is a direct child (CRIT-X-1 sanity guards)
- re-resolve cfg + apply ``--override`` (allow drift)
- allocate ``cfg_resolved_version = N+1`` under the allocator flock so
  two parallel resumes can't collide on N (HIGH-3-A)
- transition metadata.status to ``running`` via the resume schema
  exception (CRIT-2-A); ``'running' already`` warns + no-op
- preserve metadata.timestamp / metadata.exit_code; H-3
  ``wall_seconds`` overwrite happens at Phase C close, not here

The version field is bumped HERE (Phase A resume) and propagated to
Phase B via the new :class:`SetupState.cfg_resolved_version` field;
Phase B then suffixes filenames as ``cfg_resolved_v<N>.toml`` /
``cfg_leaf_v<N>.toml`` (spec §Resume 语义 pair-versioning).

Spec cross-refs: §Resume 语义 (full); §Resume 语义 HIGH-2-C leaf cfg req;
§Resume 语义 cfg_resolved_v<N> + paired cfg_leaf_v<N>; §Resume 语义 HIGH-3-A
flock'd N glob/write; §Resume 语义 CRIT-6-A cfg_resolved_version truth;
§Resume 语义 status transition + preserved timestamp/exit_code;
§metadata.toml 字段 H-3 wall_seconds (last attempt); §Resume 例外规则 CRIT-2-A exceptions;
§HIGH-2-D authoritative-host marker (T-13).
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
from tools.runs._train.cfg_toml import dict_to_toml
from tools.runs._train.setup import (
    SetupState,
    _extract_leaf_label,
    _validate_run_label,
    _verify_authoritative_host,
    _verify_repo_root,
)
from tools.runs._train.snapshot import _verify_round_trip, _versioned_filenames
from training.core.config.loader import _apply_overrides, load_with_extends

# Matches cfg_resolved.toml (v1) and cfg_resolved_v<N>.toml (vN, N>=2).
# Anchored to ^ / $ so only the canonical filenames count toward N
# allocation — a stale backup like ``cfg_resolved.toml.bak`` cannot
# bump the version.
_CFG_RESOLVED_V_RE = re.compile(r'^cfg_resolved_v(\d+)\.toml$')


def phase_a_resume(args: argparse.Namespace) -> SetupState:
    """Resume Phase A entry — replaces fresh allocate+mkdir with reuse+revalidate.

    Lifecycle (spec §Resume 语义):

    1. Infer ``artifacts_dir = ckpt.parent.parent`` (ckpts/ is a direct
       child of the per-run dir).
    2. Validate ``<cfg>`` exists + is a file (HIGH-2-C — no
       "pure ckpt" resume).
    3. Validate ``<artifacts_dir>/metadata.toml`` exists +
       ``<artifacts_dir>/ckpts/`` is a child dir.
    4. Re-resolve cfg via ``load_with_extends`` + apply ``--override``
       (allow drift; spec §Resume 语义).
    5. Re-validate ``run_label`` regex post-resolve (defense in depth
       — leaf cfg might have changed since the original train run).
    6. Allocate ``cfg_resolved_version = max(existing) + 1`` under the
       global allocator flock. **Under the same lock**, write the
       paired ``cfg_leaf_v<N>.toml`` + ``cfg_resolved_v<N>.toml`` AND
       bump metadata — spec §Resume 语义 binds glob + write + bump as one
       critical section (splitting the vN write out post-lock opens
       the v1 race window where two threads both glob N=2 and overwrite
       each other; see ``_bump_metadata_for_resume`` docstring).
    7. ``'running' already`` → warn no-op + continue (spec §CRIT-2-A);
       otherwise apply resume status transition via
       :func:`schema.validate_transition` ``resume=True``.
    8. Metadata write (status='running', cfg_resolved_version=N,
       cfg_file=new leaf path). ``timestamp`` / ``exit_code`` preserved
       (spec §Resume 语义). ``wall_seconds`` reset to 0.0 — overwritten at
       Phase C close (H-3).

    Returns the :class:`SetupState` for Phase B. Phase B reads
    ``state.cfg_resolved_version`` to suffix filenames.
    """
    _verify_repo_root(Path.cwd())

    ckpt_path = Path(args.resume)
    cfg_path = Path(args.cfg)

    # Step 2 (HIGH-2-C): leaf cfg must be present + readable.
    # Pinned wording so test_train_resume.py's stderr assertion stays
    # stable across cosmetic edits.
    if not cfg_path.exists() or not cfg_path.is_file():
        print(
            f'tools.runs.train: leaf cfg 缺失,不支持纯 ckpt 续训(必须提供 cfg 才能 resume): {cfg_path}',
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Step 1 + 3: artifacts_dir inference (ckpt convention is
    # ``<artifacts_dir>/ckpts/ckpt_<n>.pt`` per T-06) + structural
    # sanity guards. The ckpt file itself is checked lazily by
    # paradigm's run_pipeline.try_resume; here we only require the
    # registered-run structure (metadata.toml + ckpts/) so a typo
    # cannot silently scribble vN files into an unrelated dir.
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

    # Spec §HIGH-2-D — post-metadata-read / pre-allocator-lock per T-12 handoff symmetry.
    _verify_authoritative_host(Path.cwd())

    # Step 4: re-resolve cfg + apply --override (spec §Resume 语义: cfg
    # drift across resume is allowed by design).
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

    # Step 5: post-resolve regex re-validate (cfg drift allowed; bad
    # run_label not — would break dir-name convention).
    resolved_meta = cfg_resolved.get('meta')
    resolved_label = resolved_meta.get('run_label') if isinstance(resolved_meta, dict) else None
    _validate_run_label(resolved_label, source='resolved cfg.meta.run_label')

    # Step 6: N allocation + paired vN write + metadata bump all under
    # the global allocator flock (spec §Resume 语义 HIGH-3-A). Cross-dir
    # resumes serialize too — over-locks but spec-literal.
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
        _bump_metadata_for_resume(
            artifacts_dir=artifacts_dir,
            metadata_path=metadata_path,
            cfg_path=cfg_path,
            cfg_resolved_version=version,
            cfg_leaf_bytes=leaf_bytes,
            cfg_resolved=cfg_resolved,
            repo_root=repo_root,
        )

    # Re-read updated metadata so ``timestamp_utc`` single-sources the
    # original (spec §Resume 语义: timestamp NOT reset on resume).
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

    Algorithm (spec §Resume 语义):
    - If only ``cfg_resolved.toml`` exists (no vN files) → return 2.
    - Else N = max(existing vN) + 1 across all ``cfg_resolved_v<N>.toml``.
    - If neither the base file nor any vN exists → return 2 anyway
      (defensive: a partially-recovered dir where the base file got
      deleted; bumping straight to v2 keeps the audit trail forward-
      only, matching spec §Resume 语义 "highest version is truth").

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
    cfg_leaf_bytes: bytes,
    cfg_resolved: dict,
    repo_root: Path,
) -> None:
    """Write cfg_leaf_v<N>, cfg_resolved_v<N>, and bumped metadata.

    Called under the allocator flock so the full critical section
    (glob → write pair → metadata bump) cannot interleave with a
    parallel resume (spec §Resume 语义). The per-run metadata lock acquired
    inside ``write_metadata_atomic`` guards a different file, so no
    self-deadlock. Steps: (1) write ``cfg_leaf_v<N>.toml``;
    (2) write ``cfg_resolved_v<N>.toml`` via ``dict_to_toml`` +
    round-trip verify (catches emitter bugs at write time, mirroring
    fresh-path Phase B); (3) ``write_metadata_atomic`` with
    status='running' / cfg_resolved_version=N / cfg_file=leaf path.

    Failure: partial state survives (registered dir, not orphan).
    Operator re-runs; the failed vN files become audit trail and the
    next attempt allocates vN+1. Spec §单命令 atomic lifecycle cleanup applies only to
    the fresh path.
    """
    current = schema.load_file(metadata_path)

    # Spec §CRIT-2-A: 'running' already → warn + no-op metadata transition.
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

    # Step 1-2: write paired vN files INSIDE the allocator lock.
    # _verify_round_trip + _versioned_filenames imported from
    # snapshot.py to single-source the emitter-bug guard + filename
    # convention between fresh and resume paths.
    leaf_name, resolved_name = _versioned_filenames(cfg_resolved_version)
    (artifacts_dir / leaf_name).write_bytes(cfg_leaf_bytes)
    resolved_text = dict_to_toml(cfg_resolved)
    _verify_round_trip(resolved_text, cfg_resolved)
    (artifacts_dir / resolved_name).write_text(resolved_text, encoding='utf-8')

    # Step 3: metadata bump.
    cfg_file_rel = normalize_repo_relative(cfg_path, repo_root, label='cfg')

    updated = schema.RunMetadata(
        run_id=current.run_id,
        timestamp=current.timestamp,  # spec §Resume 语义 preserved
        cfg_file=cfg_file_rel,
        cfg_resolved_version=cfg_resolved_version,
        git_commit=current.git_commit,  # first-train constant
        host=current.host,
        status='running',
        artifacts_dir=current.artifacts_dir,
        wall_seconds=0.0,  # spec §metadata.toml 字段: overwritten at close
        exit_code=current.exit_code,  # spec §Resume 语义 preserved
        notes=current.notes,
    )
    write_metadata_atomic(artifacts_dir, updated)
