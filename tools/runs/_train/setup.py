"""tools.runs._train.setup — Phase A lifecycle (steps 0-3).

Internal module — callers must use :mod:`tools.runs.train` (the public
entry shell). Split out of the original monolithic ``train.py`` per
the T-08 quality review I-1 ``_train/`` sub-package precedent (see
also ``_helpers/`` package pattern from T-04), to keep each file under
the 300-line pre-commit hook budget once Phase B/C/D land in T-09-T-13.

Spec cross-refs (``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`` 主卷
+ ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design-rollout.md`` 续卷):

- §Architecture step 0-3
- §单命令 atomic lifecycle CRIT-1-B run_label regex
- §单命令 atomic lifecycle HIGH-2-A artifacts mkdir
- §单命令 atomic lifecycle CRIT-1-A 临界区 mkdir-O_EXCL
- §单命令 atomic lifecycle HIGH-2-B failure cleanup rmtree
- §单命令 atomic lifecycle HIGH-1-A ``<label>`` from resolved cfg
- §单命令 atomic lifecycle HIGH-X-3 UTC ts single-source (metadata.timestamp ↔ dir ts)
"""

from __future__ import annotations

import argparse
import re
import shutil
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.runs.helpers import allocate_nnn
from training.core.config.loader import _apply_overrides, load_with_extends


# Spec §单命令 atomic lifecycle — pinned wording. Same regex elsewhere in the spec
# is the source of truth; any drift here must update both call sites.
_RUN_LABEL_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


@dataclass(frozen=True)
class SetupState:
    """Phase A output handed to Phase B (T-09) / C (T-10).

    8 fields (6 fresh-path + 2 resume-context). ``timestamp_utc`` is
    the single source that **both** the dir-name ``<ts>`` segment and
    the future ``metadata.timestamp`` field derive from (spec §单命令 atomic lifecycle —
    "single source"; avoids midnight-UTC drift between two separate
    ``datetime.now()`` calls).

    Resume-context fields (T-12):

    - ``cfg_resolved_version``: which ``cfg_resolved_v<N>.toml`` /
      ``cfg_leaf_v<N>.toml`` Phase B writes (and records in metadata
      ``cfg_resolved_version``). Fresh path = 1 (writes the unsuffixed
      ``cfg_resolved.toml`` / ``cfg_leaf.toml``); resume path = N+1
      computed under the allocator lock (spec §Resume 语义 CRIT-6-A).
    - ``resume_ckpt_path``: ``Path`` for Phase C to pass through to
      ``run_pipeline(resume_from=...)``; ``None`` on fresh path.

    Option B chosen over a parallel ``ResumeState`` dataclass (Option
    C) because Phase B's version-aware file-naming logic is naturally
    parameterized by ``cfg_resolved_version`` — keeping it inside the
    same handoff record means callers don't have to plumb two
    different state shapes through ``main()``.
    """

    artifacts_dir: Path
    cfg_resolved: dict
    cfg_leaf_bytes: bytes
    nnn: int
    label: str
    timestamp_utc: datetime
    cfg_resolved_version: int = 1
    resume_ckpt_path: Path | None = None


def _validate_run_label(label: Any, *, source: str) -> str:
    """Enforce spec §单命令 atomic lifecycle regex; raise SystemExit(2) with spec wording.

    ``source`` distinguishes the failure context in stderr (e.g.
    ``'resolved cfg.meta.run_label'`` vs ``'leaf cfg.meta.run_label'``)
    so a regex failure caused by ``--override meta.run_label=...`` is
    diagnosable without re-running. Non-str / missing values are
    rendered as ``'<missing>'`` / ``'<int 42>'`` etc — silent
    string-coercion would mask a cfg bug (CLAUDE.md §3 "意外输入必须抛异常").
    """
    if isinstance(label, str) and _RUN_LABEL_RE.match(label):
        return label
    if not isinstance(label, str):
        display = '<missing>' if label is None else f'<{type(label).__name__} {label!r}>'
    else:
        display = repr(label)
    print(
        f'tools.runs.train: {source} {display} 不符合 regex '
        '^[a-zA-Z0-9_-]{1,64}$;路径 traversal / shell metachar / 空 / 超长 均拒',
        file=sys.stderr,
    )
    raise SystemExit(2)


def _extract_leaf_label(leaf_bytes: bytes, cfg_path: Path) -> Any:
    """Read leaf-only ``cfg.meta.run_label`` from already-captured bytes.

    Bytes come from step 1 capture (not a fresh re-read) so the
    pre-resolve validate observes exactly what step 4's
    ``cfg_leaf.toml`` will later snapshot — no race window where the
    file mutates between regex-check and snapshot.
    """
    try:
        import tomllib
    except ImportError:  # pragma: no cover — Python <3.11 fallback
        import tomli as tomllib  # type: ignore
    try:
        data = tomllib.loads(leaf_bytes.decode('utf-8'))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        print(f'tools.runs.train: cfg {cfg_path} TOML decode failed: {e}', file=sys.stderr)
        raise SystemExit(2) from e
    meta = data.get('meta')
    if not isinstance(meta, dict):
        return None
    return meta.get('run_label')


def _verify_repo_root(cwd: Path) -> None:
    """Verify cwd looks like the gicg_mono repo root.

    Production caller invoked from a subdir (e.g. ``cd tools && python -m
    tools.runs.train ...``) would silently root ``artifacts/`` at the
    wrong dir — guard prevents the silent misdirection by sanity-checking
    that ``tools/runs/`` lives under cwd.
    """
    if not (cwd / 'tools' / 'runs').is_dir():
        raise SystemExit(f'tools.runs.train must run from repo root; cwd={cwd} lacks tools/runs/')


def _verify_authoritative_host(repo_root: Path) -> None:
    """Enforce spec §HIGH-2-D authoritative-host marker.

    ``artifacts/.authoritative_host`` records the hostname allowed to
    allocate new NNN. Absent → allow (§HIGH-2-D); content == ``gethostname()``
    → allow (§HIGH-2-D); mismatch → ``SystemExit(2)`` with §HIGH-2-D pinned
    wording. ``.strip()`` tolerates ``echo > marker`` trailing newlines.

    Marker does NOT cross-host sync (§HIGH-2-D rsync exclude).
    Called from both :func:`phase_a_setup` (post-cfg-validate /
    pre-leaf-bytes per §HIGH-2-D) and :func:`._train.resume.phase_a_resume`
    (post-metadata-read / pre-allocator-lock, T-12 handoff symmetry).
    The ``tools.runs.sync init-authoritative`` writer is T-19 scope.
    """
    marker_path = repo_root / 'artifacts' / '.authoritative_host'
    if not marker_path.is_file():
        return
    content = marker_path.read_text(encoding='utf-8').strip()
    current = socket.gethostname()
    if content == current:
        return
    print(
        f'tools.runs.train: this host is pull-only; cannot allocate new NNN. '
        f'To make this host authoritative, run tools.runs.sync init-authoritative '
        f'(marker says: {content!r}, this host: {current!r})',
        file=sys.stderr,
    )
    raise SystemExit(2)


def phase_a_setup(args: argparse.Namespace) -> SetupState:
    """Steps 0-3: validate → capture → resolve → mkdir per-run dir.

    Validation strategy: regex-check the leaf cfg's ``meta.run_label``
    first (cheap, fails fast on obvious garbage), then re-check the
    **resolved** value after ``--override`` apply. Spec §单命令 atomic lifecycle specifies
    the dir name comes from the resolved value, so an override like
    ``--override meta.run_label=../etc`` must be rejected even when the
    leaf cfg passes — the second check covers that. The first check
    short-circuits before we do any cfg load / extends resolution work
    when the leaf is already broken.
    """
    _verify_repo_root(Path.cwd())
    cfg_path = Path(args.cfg)
    if not cfg_path.exists():
        print(f'tools.runs.train: cfg {cfg_path} not found', file=sys.stderr)
        raise SystemExit(2)
    if not cfg_path.is_file():
        print(f'tools.runs.train: cfg {cfg_path} is not a regular file', file=sys.stderr)
        raise SystemExit(2)

    # Spec §HIGH-2-D "step 0 后,step 1 前" — reject pull-only
    # replicas before any I/O (read_bytes / mkdir / NNN allocate).
    _verify_authoritative_host(Path.cwd())

    # Step 1: capture leaf bytes FIRST (spec §单命令 atomic lifecycle "read_bytes 立即,防 cfg edit race").
    # Order matters: we read bytes before any other I/O on cfg_path so the
    # subsequent TOML parse / extends resolve observes the same content
    # snapshot regardless of concurrent editor saves.
    leaf_bytes = cfg_path.read_bytes()

    # Step 0 (pre-resolve, leaf-only): fail fast on obvious garbage in
    # the leaf cfg's run_label. The post-resolve check below is the
    # authoritative guard; this just trims feedback latency.
    leaf_label = _extract_leaf_label(leaf_bytes, cfg_path)
    _validate_run_label(leaf_label, source='leaf cfg.meta.run_label')

    # Step 2: resolve extends chain + apply --override list.
    # Using ``load_with_extends`` (public-by-comment per loader.py line 95
    # docstring) for extends + ``_apply_overrides`` (internal but
    # canonical override parser — duplicating its int/float/bool/str
    # coercion rules here would invite drift). Both raise ValueError on
    # malformed input; we convert to SystemExit(2) per CLI convention.
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

    # Step 0 (post-resolve, authoritative): re-validate. Spec §单命令 atomic lifecycle —
    # dir name <label> is the POST-override value, so this is the check
    # whose pass/fail decides whether mkdir proceeds.
    resolved_meta = cfg_resolved.get('meta')
    resolved_label = resolved_meta.get('run_label') if isinstance(resolved_meta, dict) else None
    label = _validate_run_label(resolved_label, source='resolved cfg.meta.run_label')

    # Step 2.5: ensure artifacts/ exists. Fresh repo first-train would
    # otherwise see allocator's mkdir(parents=False) succeed (it
    # creates artifacts/ via flock open path) — but caller-side mkdir
    # of the per-run dir would still fail if artifacts/ disappeared
    # between allocator yield and caller mkdir. Explicit step 2.5
    # belt-and-braces matches spec §单命令 atomic lifecycle.
    repo_root = Path.cwd()
    artifacts_root = repo_root / 'artifacts'
    artifacts_root.mkdir(parents=True, exist_ok=True)

    # Step 3: allocate NNN under flock + mkdir per-run dir O_EXCL.
    # UTC ts truncated to minute (dir name precision); single-sourced
    # so T-09 metadata.timestamp ↔ dir-name ts align by construction
    # (spec §单命令 atomic lifecycle — no parallel ``datetime.now()`` calls).
    timestamp_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    ts_str = timestamp_utc.strftime('%Y%m%d%H%M')

    artifacts_dir: Path | None = None
    nnn_final: int | None = None
    # EEXIST retry outer loop per spec §Atomic allocator / allocator.py docstring
    # Bound the loop so a catastrophic FS bug can't infinite-
    # spin (allocator's flock budget is 10; matching that here keeps
    # operator mental model simple).
    max_eexist_retries = 10
    for attempt in range(max_eexist_retries):
        with allocate_nnn(repo_root) as nnn:
            candidate = artifacts_root / f'{ts_str}_{nnn:06d}_{label}'
            try:
                candidate.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                # Exit ``with`` (flock release) → re-enter on next iter.
                # allocator's re-glob will observe the colliding dir and
                # the next NNN will skip past it.
                continue
            artifacts_dir = candidate
            nnn_final = nnn
            break
    if artifacts_dir is None or nnn_final is None:
        raise RuntimeError(
            f'tools.runs.train: NNN allocator exhausted {max_eexist_retries} '
            f'EEXIST retries (label={label!r}, ts={ts_str}); inspect artifacts/ for '
            'rogue dirs colliding on every allocated NNN'
        )

    # State assembly is dataclass __init__ — if it raises (it shouldn't,
    # all fields are pre-validated) we still own the orphan dir and
    # must rmtree before propagating. Spec §单命令 atomic lifecycle.
    try:
        return SetupState(
            artifacts_dir=artifacts_dir,
            cfg_resolved=cfg_resolved,
            cfg_leaf_bytes=leaf_bytes,
            nnn=nnn_final,
            label=label,
            timestamp_utc=timestamp_utc,
        )
    except BaseException:
        # Surface the original error, not the cleanup error.
        # Bare `raise` re-raises the original including KeyboardInterrupt.
        # Cleanup-error stderr print is informational, not an exception path.
        try:
            shutil.rmtree(artifacts_dir, ignore_errors=False)
        except OSError as cleanup_err:
            print(
                f'tools.runs.train: orphan dir cleanup failed for {artifacts_dir}: '
                f'{cleanup_err}; manual rmtree required',
                file=sys.stderr,
            )
        raise
