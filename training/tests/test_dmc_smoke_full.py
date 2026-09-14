"""DMC paradigm smoke_full — full driver e2e + ckpt save/load (A1.6).

OpenSpec ref: ``openspec/changes/paradigm-smoke-full-tier/specs/
training-architecture/spec.md`` invariant A1.6 + tools/runs/ clean-slate
redesign spec ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-
design.md`` §Per-run dir / §Resume 语义.

Verifies the full `tools.runs.train configs/dmc/smoke_full.toml` driver path:

- Subprocess train run completes (terminates per total_frames=2500 →
  ~190 step on Mac CPU ~2.5 min wall, well under 15 min hard cap)
- `CheckpointManager` writes ≥ 2 ckpt files under ``ckpts/`` subdir
  (T-06 layout: ``<artifacts>/ckpts/ckpt_*.pt`` + ``ckpts/latest.pt``)
- `metrics.jsonl` present at ``<artifacts>/`` root
- Resume subprocess from lex-first ckpt exits 0, bumps
  ``metadata.cfg_resolved_version → 2``, writes ``cfg_resolved_v2.toml``
  + ``cfg_leaf_v2.toml``, and produces ≥ 1 new ckpt file in same
  artifacts dir.

Resume strategy: bump ``paradigm.dmc.total_frames`` from 2500 → 5000
on resume so the resumed run has room to advance past existing ckpt
steps regardless of where the initial run terminated (machine load /
collector ramp jitter would otherwise make lex-first ckpt resume
flaky — initial run may stop at step ~190 with 6 ckpts {30,60,90,
120,150,180} where lex-first = ckpt_120, and resuming from step 120
with the same total_frames budget already half-consumed leaves only
1000 more frames → resumed run terminates around step 180-200 →
overwrites existing files only, no new). The total_frames bump is
the DMC analogue of BC's n_epochs bump + PPO's total_iterations bump
+ CFR's n_iterations bump (all 4 fixed-budget paradigms need a
terminus bump on resume to deterministically produce new ckpts).
"""

from __future__ import annotations

import pytest

from training.tests.smoke_full_template import (
    REPO_ROOT,
    resume_and_continue,
    run_paradigm_train_via_driver,
    verify_ckpt_files,
)


@pytest.mark.smoke_full
def test_dmc_smoke_full(tmp_path) -> None:
    """DMC full smoke — driver train (≥ 100 step) + ckpt save + resume."""
    cfg = REPO_ROOT / 'configs' / 'dmc' / 'smoke_full.toml'
    assert cfg.exists(), f'cfg missing: {cfg}'

    # Phase 1: train run → artifacts dir + multiple ckpt files.
    artifacts = run_paradigm_train_via_driver(cfg, tmp_path)
    ckpts = verify_ckpt_files(artifacts, expected_min_count=2)

    # Phase 2: resume from lex-first ckpt + bump total_frames so the
    # resumed run has frame budget to advance past existing ckpt steps
    # (otherwise resume can overwrite existing files only — flaky on
    # machine load jitter; see module docstring).
    new_ckpts = resume_and_continue(
        ckpts[0],
        extra_overrides=['paradigm.dmc.total_frames=5000'],
    )
    old_steps = {int(p.stem.split('_')[1]) for p in ckpts}
    new_steps = {int(p.stem.split('_')[1]) for p in new_ckpts}
    assert max(new_steps) > max(old_steps), 'resume must advance beyond the prior final checkpoint'
