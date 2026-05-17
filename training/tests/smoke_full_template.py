"""smoke_full template — full-tier paradigm smoke helpers (D-601 / A1.6).

OpenSpec ref: ``openspec/changes/paradigm-smoke-full-tier/specs/
training-architecture/spec.md`` invariant A1.6.

This module owns the 3 subprocess helpers used by 5 paradigm
``test_<paradigm>_smoke_full.py`` files:

1. ``run_paradigm_train_via_driver(cfg, artifacts_root)`` —
   subprocess-invoke ``python -m tools.run <cfg> --override
   checkpoint.artifacts_root=<tmp>`` per SF-101 / SF-106. Returns the
   driver-created artifacts dir.
2. ``verify_ckpt_files(artifacts, expected_min_count)`` — assert
   ``ckpt_*.pt`` files + ``latest.pt`` written by ``CheckpointManager``
   per A1.6.2.
3. ``resume_and_continue(ckpt_file)`` — subprocess-invoke
   ``python -m tools.run <cfg> --resume <ckpt>``,returns new ckpt
   list post-resume per A1.6.3 / SF-102 (functional only,not
   bit-identical).

REUSE FIRST per D-601 revision: zero new ckpt save/load/dispatch
logic. Full subprocess调用 production ``tools.run`` driver +
``training/core/checkpoint.py::CheckpointManager``.

Scope caveat (M5 single-sourced timestamp):
smoke_full tests subprocess-invoke `tools.run` WITHOUT `--run-id` (no
register/complete round-trip — tmp_path artifacts dir is throwaway).
The dir prefix therefore uses `datetime.now()` local, NOT a metadata-
sourced UTC timestamp. This is intentional — there's no cross-host
metadata consumer for these dirs, so single-sourcing has no value
here. Production runs use `tools.run --run-id <id>` and get the
UTC-strftime single-source path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


# Repo root resolution: walk up from this test file looking for
# `gicg_engine/` (canonical repo marker). Compatible with worktree
# layout (`.claude/worktrees/.../training/tests/`) — parents[2] in
# worktree resolves to worktree root, not main repo. Tests run with
# `cwd=worktree_root` so `tools.run` resolves relative paths correctly.
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


def run_paradigm_train_via_driver(
    cfg_path: Path,
    tmp_artifacts_root: Path,
    *,
    timeout_s: int = TRAIN_TIMEOUT_S,
    extra_overrides: list[str] | None = None,
    extra_env: Optional[dict] = None,
    max_steps: Optional[int] = None,
) -> Path:
    """Subprocess `tools.run <cfg>` with checkpoint.artifacts_root redirected.

    Args:
        cfg_path: smoke_full toml (absolute or relative to REPO_ROOT).
        tmp_artifacts_root: pytest tmp_path — driver writes
            `<tmp>/<timestamp>_<run_label>/` here per
            CheckpointManager.init_artifacts_dir.
        timeout_s: subprocess wall hard cap (default 15 min per SF-104).
        extra_overrides: paradigm-specific `key.path=value` overrides
            appended after the mandatory ``checkpoint.artifacts_root``
            override (each prefixed with its own ``--override`` flag,
            since ``tools.run`` uses ``action='append'``). Backward-
            compatible: default ``None`` → behaviour unchanged. Used by
            BC smoke_full to inject the on-the-fly NPZ dataset path
            (``paradigm.bc.dataset_path=<tmp>/dataset.npz``) per
            ``bc-smoke-dataset-fixture``.
        extra_env: optional dict merged into subprocess env (e.g.
            ``{'GICG_CFR_SMOKE_STUB_BUFFER': '1'}`` for CFR stub buffer
            injection per cfr-driver-buffer-multihead-fix C6.4). Parent
            process env untouched.
        max_steps: optional ``tools.run --max-steps N`` override for
            paradigm whose terminus is step-based (e.g. CFR
            ``n_iterations``) — lets initial run stop early so resume
            can produce strictly new ckpt files at later steps.

    Returns:
        The unique artifacts subdir created by driver.

    Raises:
        subprocess.CalledProcessError if `tools.run` exits non-zero.
        RuntimeError if driver did not create exactly one artifacts dir.
    """
    cfg_abs = cfg_path if cfg_path.is_absolute() else REPO_ROOT / cfg_path
    tmp_root_abs = tmp_artifacts_root.resolve()
    tmp_root_abs.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        '-m',
        'tools.run',
        str(cfg_abs),
        '--override',
        f'checkpoint.artifacts_root={tmp_root_abs}',
    ]
    for ov in extra_overrides or []:
        cmd.extend(['--override', ov])
    if max_steps is not None:
        cmd.extend(['--max-steps', str(max_steps)])
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=True,
        timeout=timeout_s,
        env=env,
    )
    # CheckpointManager.init_artifacts_dir creates `<root>/<ts>_<run_label>/`.
    dirs = [d for d in tmp_root_abs.iterdir() if d.is_dir()]
    if len(dirs) != 1:
        raise RuntimeError(
            f'smoke_full: expected single artifacts dir under {tmp_root_abs}, got {len(dirs)}: {[d.name for d in dirs]}'
        )
    return dirs[0]


def verify_ckpt_files(artifacts: Path, *, expected_min_count: int = 2) -> list[Path]:
    """Verify CheckpointManager wrote ≥ N ckpt + latest.pt + metrics.jsonl.

    Args:
        artifacts: dir returned by `run_paradigm_train_via_driver`.
        expected_min_count: A1.6.2 requires ≥ 2 ckpt files within run.

    Returns:
        Sorted list of ckpt files found (for downstream resume targeting).

    Raises:
        AssertionError on any A1.6.2 violation.
    """
    ckpts = sorted(artifacts.glob('ckpt_*.pt'))
    assert len(ckpts) >= expected_min_count, (
        f'smoke_full A1.6.2: expected ≥ {expected_min_count} ckpt files in '
        f'{artifacts}, got {len(ckpts)}: {[c.name for c in ckpts]}. '
        f'Check `[checkpoint] save_every` cadence in smoke_full toml + '
        f'paradigm step_schedule terminus.'
    )
    latest = artifacts / 'latest.pt'
    assert latest.exists(), f'smoke_full A1.6.2: latest.pt missing in {artifacts}'
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
    """Subprocess `tools.run <cfg> --resume <ckpt>` + verify new ckpts.

    Recovers the paradigm + smoke_full cfg path from the artifacts dir's
    `cfg_snapshot.json` (CheckpointManager writes this at init).

    Per CheckpointManager.init_artifacts_dir resume_from branch: the
    artifacts_dir is REUSED (parent of ckpt_file), so post-resume ckpts
    land in the same dir.

    Per SF-102 functional verify: assert subprocess exit 0 + new ckpt
    file count > pre-resume. Do NOT bit-identical compare weights.

    Args:
        ckpt_file: a ckpt_*.pt file produced by the train run.
        timeout_s: subprocess wall hard cap (default 10 min).
        extra_overrides: paradigm-specific `key.path=value` overrides
            to re-apply on resume (same semantics as
            ``run_paradigm_train_via_driver``). BC smoke_full passes its
            NPZ dataset_path here so the resumed run can re-load the
            same fixture dataset (cfg_snapshot.json captures the merged
            cfg but the actual ``--override`` flag must be re-supplied
            since ``tools.run --resume`` re-loads the cfg from disk).

    Returns:
        Sorted ckpt list post-resume.

    Raises:
        subprocess.CalledProcessError on subprocess non-zero exit.
        FileNotFoundError if cfg_snapshot.json missing.
        AssertionError if no new ckpt files post-resume.
    """
    artifacts = ckpt_file.parent
    snap_path = artifacts / 'cfg_snapshot.json'
    if not snap_path.exists():
        raise FileNotFoundError(
            f'smoke_full: cfg_snapshot.json missing in {artifacts} — driver did not init artifacts dir properly'
        )
    snap = json.loads(snap_path.read_text())
    paradigm = snap['meta']['paradigm']
    cfg_path = REPO_ROOT / 'configs' / paradigm / 'smoke_full.toml'
    if not cfg_path.exists():
        raise FileNotFoundError(f'smoke_full: resume needs configs/{paradigm}/smoke_full.toml, not found at {cfg_path}')

    pre_resume_ckpts = sorted(artifacts.glob('ckpt_*.pt'))
    cmd = [
        sys.executable,
        '-m',
        'tools.run',
        str(cfg_path),
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
        cwd=str(REPO_ROOT),
        check=True,
        timeout=timeout_s,
        env=env,
    )

    post_resume_ckpts = sorted(artifacts.glob('ckpt_*.pt'))
    assert len(post_resume_ckpts) > len(pre_resume_ckpts), (
        f'smoke_full A1.6.3: expected new ckpt(s) after resume from '
        f'{ckpt_file.name}, but ckpt count unchanged ({len(pre_resume_ckpts)} → '
        f'{len(post_resume_ckpts)}). Resume subprocess succeeded but driver '
        f'did not advance state.step past last_ckpt_at_step + save_every. '
        f'Bump terminus in smoke_full toml.'
    )
    return post_resume_ckpts
