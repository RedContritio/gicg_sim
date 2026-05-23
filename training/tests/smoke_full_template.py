"""smoke_full template — full-tier paradigm smoke helpers (D-601 / A1.6).

OpenSpec ref: ``openspec/changes/paradigm-smoke-full-tier/specs/
training-architecture/spec.md`` invariant A1.6 + tools/runs/ clean-slate
redesign spec ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-
design.md`` §迁移策略 / §Per-run dir.

This module owns the 3 subprocess helpers used by 5 paradigm
``test_<paradigm>_smoke_full.py`` files:

1. ``run_paradigm_train_via_driver(cfg, workspace, ...)`` — subprocess
   ``python -m tools.runs.train <cfg>`` with cwd pinned to an isolated
   ``workspace`` dir (symlinked subset of repo). Returns the per-run
   artifacts dir under ``<workspace>/artifacts/<ts>_<NNN>_<label>/``
   that Phase A allocated.
2. ``verify_ckpt_files(artifacts, expected_min_count)`` — assert
   ``ckpts/ckpt_*.pt`` + ``ckpts/latest.pt`` written by
   ``CheckpointManager`` per T-06 ckpts/ subdir layout.
3. ``resume_and_continue(ckpt_file)`` — subprocess
   ``python -m tools.runs.train <cfg> --resume <ckpt>``,verifies the
   resume path bumped ``metadata.cfg_resolved_version`` to 2 and wrote
   ``cfg_resolved_v2.toml`` + ``cfg_leaf_v2.toml`` per T-12. Returns
   the post-resume ckpt list.

T-25 rewrite (2026-05-18 tools/runs/ clean-slate redesign):

- ``--max-steps`` flag deleted (spec C-1) — cap steps via cfg
  ``--override paradigm.<X>.total_frames=N`` etc instead.
- ``cfg.checkpoint.artifacts_root=<tmp>`` override is NOT honored by
  ``tools.runs.train`` (Phase A hardcodes ``cwd/artifacts/``); workspace
  isolation now uses ``cwd=<tmp>/workspace/`` with symlinks back to
  repo subdirs (``tools/``, ``training/``, ``gicg_env/``, ``data/``,
  ``gicg_engine/``, ``configs/``) so the per-run dir lands under
  ``<workspace>/artifacts/`` and production ``artifacts/`` stays clean.
- Resume path now reads from ``<artifacts_dir>/ckpts/`` per T-06 +
  T-12 layout.
- Resume verifies ``cfg_resolved_v2.toml`` exists + ``metadata.cfg_
  resolved_version == 2`` (Phase A resume bumps both atomically under
  the allocator flock).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Optional


# Repo root resolution: walk up from this test file looking for
# ``gicg_engine/`` (canonical repo marker). Compatible with worktree
# layout (``.claude/worktrees/.../training/tests/``) — parents[2] in
# worktree resolves to worktree root, not main repo.
def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / 'gicg_engine').is_dir() and (p / 'tools').is_dir():
            return p
    raise RuntimeError(f'smoke_full_template: cannot locate repo root from {here}')


REPO_ROOT = _find_repo_root()

# Subprocess timeouts (per SF-104). Train: 15 min hard cap (target ≤ 8 min).
# Resume: 10 min (resumes from existing ckpt, less to do).
TRAIN_TIMEOUT_S = 900
RESUME_TIMEOUT_S = 600

# Repo subdirs the subprocess needs reachable from cwd. ``tools/``
# satisfies ``_verify_repo_root`` + ``python -m tools.runs.train``
# import resolution. ``training/`` + ``gicg_env/`` are paradigm /
# engine imports. ``data/`` is read by env factory (cfg
# ``scenario.data_dir = "data"`` is cwd-relative). ``gicg_engine/``
# kept for symmetry. ``configs/`` is NOT symlinked — see make_workspace.
_WORKSPACE_SYMLINKS = ('tools', 'training', 'gicg_env', 'data', 'gicg_engine')


def make_workspace(tmp_path: Path) -> Path:
    """Build an isolated workspace under ``tmp_path/workspace/``.

    Layout:

    - ``workspace/tools`` / ``training`` / ``gicg_env`` / ``data`` /
      ``gicg_engine`` — symlinks to repo subdirs (import + data
      resolution).
    - ``workspace/configs/`` — **real copy** of repo's ``configs/``
      (not symlink). Reason: ``tools.runs.train`` Phase B passes the
      cfg path through ``normalize_repo_relative`` which calls
      ``Path.resolve()`` on both cfg and repo_root. A symlinked
      ``configs/`` would resolve back to ``REPO_ROOT/configs/...`` and
      fail the ``relative_to(workspace)`` check. Copying keeps the cfg
      under workspace post-resolve.

    Production ``artifacts/`` is never touched — Phase A writes under
    ``workspace/artifacts/<ts>_<NNN>_<label>/``. Caller passes the cfg
    path relative to workspace (e.g. ``configs/dmc/smoke_full.toml``)
    so Phase B sees a cfg that resolves under workspace.

    Idempotent within one ``tmp_path``.
    """
    workspace = tmp_path / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    for name in _WORKSPACE_SYMLINKS:
        target = REPO_ROOT / name
        link = workspace / name
        if link.exists() or link.is_symlink():
            continue
        link.symlink_to(target, target_is_directory=target.is_dir())
    configs_dst = workspace / 'configs'
    if not configs_dst.exists():
        # Copy the configs/ tree (small: ~5 paradigm * 3 toml each).
        shutil.copytree(REPO_ROOT / 'configs', configs_dst, symlinks=False)
    return workspace


def cfg_path_under_workspace(cfg: Path, workspace: Path) -> Path:
    """Translate a repo-absolute cfg path to its workspace counterpart.

    Tests reference cfgs as ``REPO_ROOT / 'configs' / paradigm /
    'smoke_full.toml'`` for clarity; the subprocess needs the same cfg
    routed through ``workspace/configs/<paradigm>/<name>.toml`` so Phase
    B's ``normalize_repo_relative`` accepts it. Raises ``RuntimeError``
    if the cfg is not under ``REPO_ROOT/configs``.
    """
    abs_cfg = cfg if cfg.is_absolute() else REPO_ROOT / cfg
    try:
        rel = abs_cfg.relative_to(REPO_ROOT)
    except ValueError as e:
        raise RuntimeError(f'smoke_full: cfg {abs_cfg} must live under REPO_ROOT {REPO_ROOT}') from e
    return workspace / rel


def run_paradigm_train_via_driver(
    cfg_path: Path,
    tmp_path: Path,
    *,
    timeout_s: int = TRAIN_TIMEOUT_S,
    extra_overrides: list[str] | None = None,
    extra_env: Optional[dict] = None,
) -> Path:
    """Subprocess `tools.runs.train <cfg>` under isolated workspace.

    Args:
        cfg_path: smoke_full toml (absolute or relative to REPO_ROOT).
            Passed to the subprocess as an absolute path so cwd
            (workspace symlink dir) does not affect cfg resolution.
        tmp_path: pytest tmp_path. A ``workspace/`` subdir is created
            with symlinks back to the repo; Phase A writes the per-run
            dir under ``<workspace>/artifacts/<ts>_<NNN>_<label>/``.
        timeout_s: subprocess wall hard cap (default 15 min per SF-104).
        extra_overrides: paradigm-specific ``key.path=value`` overrides
            appended after default ``--override`` flags (each prefixed
            with its own ``--override`` since ``tools.runs.train`` uses
            ``action='append'``). Used by BC smoke_full to inject the
            on-the-fly NPZ dataset path
            (``paradigm.bc.dataset_path=<tmp>/dataset.npz``).
        extra_env: optional dict merged into subprocess env (parent
            process env untouched)。 Post 2026-05-24 env-var 砍后 5 paradigm
            smoke 走 cfg-driven (CFR stub buffer via cfg.debug.cfr_smoke_stub_buffer
            baked in configs/cfr/smoke{,_full}.toml [debug])。 保留 hook 给
            future paradigm 需 unusual env propagation (e.g. PPO worker-internal
            mp.Process spawn env)。

    Returns:
        The unique per-run artifacts subdir created by Phase A under
        ``<workspace>/artifacts/<ts>_<NNN>_<label>/``.

    Raises:
        subprocess.CalledProcessError if `tools.runs.train` exits non-zero.
        RuntimeError if Phase A did not create exactly one artifacts dir.
    """
    workspace = make_workspace(tmp_path)
    cfg_in_workspace = cfg_path_under_workspace(cfg_path, workspace)
    if not cfg_in_workspace.exists():
        raise RuntimeError(
            f'smoke_full: cfg {cfg_in_workspace} not present in workspace configs copy; '
            f'check make_workspace shutil.copytree completed'
        )

    cmd: list[str] = [
        sys.executable,
        '-m',
        'tools.runs.train',
        str(cfg_in_workspace),
    ]
    for ov in extra_overrides or []:
        cmd.extend(['--override', ov])
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    subprocess.run(
        cmd,
        cwd=str(workspace),
        check=True,
        timeout=timeout_s,
        env=env,
    )
    artifacts_root = workspace / 'artifacts'
    if not artifacts_root.is_dir():
        raise RuntimeError(f'smoke_full: Phase A did not create artifacts/ under {workspace}')
    dirs = [d for d in artifacts_root.iterdir() if d.is_dir()]
    # Filter out allocator/state files that aren't per-run dirs.
    dirs = [d for d in dirs if not d.name.startswith('.')]
    if len(dirs) != 1:
        raise RuntimeError(
            f'smoke_full: expected single per-run artifacts dir under {artifacts_root}, '
            f'got {len(dirs)}: {[d.name for d in dirs]}'
        )
    return dirs[0]


def verify_ckpt_files(artifacts: Path, *, expected_min_count: int = 2) -> list[Path]:
    """Verify CheckpointManager wrote ≥ N ckpt + latest.pt + metrics.jsonl under ckpts/.

    Per T-06 layout (commit 38fddb6): all .pt files live in
    ``<artifacts>/ckpts/`` (not in ``<artifacts>/`` root). This helper
    enforces the subdir convention so a regression that flips the
    layout back to flat fails here, not later in resume.

    Args:
        artifacts: per-run dir returned by ``run_paradigm_train_via_driver``.
        expected_min_count: A1.6.2 requires ≥ 2 ckpt files within run.

    Returns:
        Sorted list of ckpt files under ``ckpts/`` (for downstream resume targeting).

    Raises:
        AssertionError on any A1.6.2 / T-06 violation.
    """
    ckpts_dir = artifacts / 'ckpts'
    assert ckpts_dir.is_dir(), (
        f'smoke_full T-06: expected ckpts/ subdir at {ckpts_dir}; '
        f'CheckpointManager.save writes ckpts under <artifacts>/ckpts/ per spec §Per-run dir.'
    )
    ckpts = sorted(ckpts_dir.glob('ckpt_*.pt'))
    assert len(ckpts) >= expected_min_count, (
        f'smoke_full A1.6.2: expected ≥ {expected_min_count} ckpt files in '
        f'{ckpts_dir}, got {len(ckpts)}: {[c.name for c in ckpts]}. '
        f'Check `[checkpoint] save_every` cadence in smoke_full toml + '
        f'paradigm step_schedule terminus.'
    )
    latest = ckpts_dir / 'latest.pt'
    assert latest.exists(), f'smoke_full A1.6.2: latest.pt missing in {ckpts_dir}'
    metrics = artifacts / 'metrics.jsonl'
    assert metrics.exists(), f'smoke_full A1.6.2: metrics.jsonl missing in {artifacts}'
    return ckpts


def resume_and_continue(
    ckpt_file: Path,
    *,
    timeout_s: int = RESUME_TIMEOUT_S,
    extra_overrides: list[str] | None = None,
    extra_env: Optional[dict] = None,
) -> list[Path]:
    """Subprocess `tools.runs.train <cfg> --resume <ckpt>` + verify new ckpts.

    Recovers (a) the paradigm + smoke_full cfg path and (b) the
    workspace (cwd) from the artifacts dir layout:

    - ``ckpt_file`` lives under ``<workspace>/artifacts/<dir>/ckpts/``
      → ``cwd = <workspace>``
    - paradigm read from ``<artifacts>/metadata.toml`` (canonical per
      T-09 Phase B); cfg located at ``configs/<paradigm>/smoke_full.toml``

    Per CheckpointManager.init_artifacts_dir resume_from branch: the
    artifacts_dir is REUSED (parent.parent of ckpt_file), so post-resume
    ckpts land in the same ``ckpts/`` subdir.

    Per T-12 cfg_resolved_v<N>: Phase A resume bumps version under the
    allocator flock and writes paired ``cfg_resolved_v2.toml`` +
    ``cfg_leaf_v2.toml`` + updates ``metadata.cfg_resolved_version=2``.
    This helper asserts all three.

    Per SF-102 functional verify: assert subprocess exit 0 + new ckpt
    file count > pre-resume. Do NOT bit-identical compare weights.

    Args:
        ckpt_file: a ckpt_*.pt file produced by the train run, lying
            under ``<workspace>/artifacts/<dir>/ckpts/``.
        timeout_s: subprocess wall hard cap (default 10 min).
        extra_overrides: paradigm-specific ``key.path=value`` overrides
            to re-apply on resume (same semantics as
            ``run_paradigm_train_via_driver``). BC / PPO smoke_full pass
            terminus-bump overrides here so the resumed run has room to
            advance past existing ckpt steps.
        extra_env: optional dict merged into subprocess env (CFR stub
            buffer must be re-injected on resume).

    Returns:
        Sorted ckpt list post-resume.

    Raises:
        subprocess.CalledProcessError on subprocess non-zero exit.
        FileNotFoundError if metadata.toml missing.
        AssertionError if cfg_resolved_v2 / metadata version not bumped
            or no new ckpt files post-resume.
    """
    artifacts = ckpt_file.parent.parent
    ckpts_dir = ckpt_file.parent
    assert ckpts_dir.name == 'ckpts', (
        f'smoke_full T-12: resume ckpt must live under <artifacts>/ckpts/, '
        f'got parent dir {ckpts_dir.name!r} for {ckpt_file}'
    )
    workspace = artifacts.parent.parent  # <workspace>/artifacts/<dir>/ckpts/<ckpt>
    metadata_path = artifacts / 'metadata.toml'
    if not metadata_path.exists():
        raise FileNotFoundError(f'smoke_full: metadata.toml missing in {artifacts} — Phase B did not write metadata')
    pre_meta = tomllib.loads(metadata_path.read_text(encoding='utf-8'))
    paradigm = pre_meta.get('cfg_file', '')
    # cfg_file is repo-relative path like 'configs/dmc/smoke_full.toml';
    # extract paradigm from path segment for resume cfg lookup.
    cfg_rel = Path(paradigm)
    if len(cfg_rel.parts) < 3 or cfg_rel.parts[0] != 'configs':
        raise RuntimeError(
            f'smoke_full: cannot infer paradigm from metadata.cfg_file={paradigm!r} '
            f'(expected configs/<paradigm>/<name>.toml)'
        )
    paradigm_name = cfg_rel.parts[1]
    cfg_repo_path = REPO_ROOT / 'configs' / paradigm_name / 'smoke_full.toml'
    if not cfg_repo_path.exists():
        raise FileNotFoundError(
            f'smoke_full: resume needs configs/{paradigm_name}/smoke_full.toml, not found at {cfg_repo_path}'
        )
    # Use the workspace's configs/ copy (same content as repo's, but
    # resolves under workspace per Phase B normalize_repo_relative).
    cfg_in_workspace = cfg_path_under_workspace(cfg_repo_path, workspace)

    pre_resume_ckpts = sorted(ckpts_dir.glob('ckpt_*.pt'))
    cmd: list[str] = [
        sys.executable,
        '-m',
        'tools.runs.train',
        str(cfg_in_workspace),
        '--resume',
        str(ckpt_file),
    ]
    for ov in extra_overrides or []:
        cmd.extend(['--override', ov])
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    subprocess.run(
        cmd,
        cwd=str(workspace),
        check=True,
        timeout=timeout_s,
        env=env,
    )

    # T-12 invariant: cfg_resolved_v2.toml + cfg_leaf_v2.toml written
    # under the allocator flock; metadata.cfg_resolved_version bumped.
    assert (artifacts / 'cfg_resolved_v2.toml').exists(), (
        f'smoke_full T-12: cfg_resolved_v2.toml missing in {artifacts} post-resume '
        f'(Phase A resume should have bumped version under allocator flock)'
    )
    assert (artifacts / 'cfg_leaf_v2.toml').exists(), (
        f'smoke_full T-12: cfg_leaf_v2.toml missing in {artifacts} post-resume'
    )
    post_meta = tomllib.loads(metadata_path.read_text(encoding='utf-8'))
    assert post_meta.get('cfg_resolved_version') == 2, (
        f'smoke_full T-12: metadata.cfg_resolved_version expected 2 post-resume, '
        f'got {post_meta.get("cfg_resolved_version")!r}'
    )

    post_resume_ckpts = sorted(ckpts_dir.glob('ckpt_*.pt'))
    assert len(post_resume_ckpts) > len(pre_resume_ckpts), (
        f'smoke_full A1.6.3: expected new ckpt(s) after resume from '
        f'{ckpt_file.name}, but ckpt count unchanged ({len(pre_resume_ckpts)} → '
        f'{len(post_resume_ckpts)}). Resume subprocess succeeded but driver '
        f'did not advance state.step past last_ckpt_at_step + save_every. '
        f'Bump terminus in smoke_full toml.'
    )
    return post_resume_ckpts
