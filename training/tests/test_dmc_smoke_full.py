"""DMC paradigm smoke_full — full driver e2e + ckpt save/load (A1.6).

OpenSpec ref: ``openspec/changes/paradigm-smoke-full-tier/specs/
training-architecture/spec.md`` invariant A1.6.

Verifies the full `tools.runs.train configs/dmc/smoke_full.toml` driver path:

- Subprocess train run completes (terminates per total_frames=2500 →
  ~190 step on Mac CPU ~2.5 min wall, well under 15 min hard cap)
- `CheckpointManager` writes ≥ 2 ckpt files (save_every=30, ~6 ckpts expected)
- `latest.pt` + `metrics.jsonl` present
- Resume subprocess from ckpts[0] (earliest ckpt at step 30) exits 0
  and produces ≥ 1 new ckpt file in same artifacts dir
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

    # Phase 2: resume from earliest ckpt → ≥ 1 new ckpt post-resume.
    new_ckpts = resume_and_continue(ckpts[0])
    assert len(new_ckpts) > len(ckpts), (
        f'expected new ckpt(s) after resume from {ckpts[0].name}, got {len(ckpts)} → {len(new_ckpts)} files'
    )
