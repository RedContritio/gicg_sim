"""AZ paradigm smoke_full — full driver e2e + ckpt save/load (A1.6).

OpenSpec ref: ``openspec/changes/paradigm-smoke-full-tier/specs/
training-architecture/spec.md`` invariant A1.6 + DECISIONS SF-105。

POST `az-resume-shape-fix` archive(2026-05-17):train + resume 全 PASS。
Resume-phase prerequisite — `make_actor_critic` 跨 subprocess 用
`HEAD_REGISTRY` insertion order 迭代 `head_kinds`(network-architecture
A12.1)— optimizer state positional mapping 保 stable across save / resume。

Prior history(now closed):

- `az-pool-spec-type-fix`(archive 2026-05-17)解锁 train-phase
- `az-resume-shape-fix`(archive 2026-05-17)解锁 resume-phase
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
def test_az_smoke_full(tmp_path) -> None:
    """AZ full smoke — driver train (≥ 100 step) + ckpt save + resume."""
    cfg = REPO_ROOT / 'configs' / 'az' / 'smoke_full.toml'
    assert cfg.exists(), f'cfg missing: {cfg}'

    artifacts = run_paradigm_train_via_driver(cfg, tmp_path)
    ckpts = verify_ckpt_files(artifacts, expected_min_count=2)

    # Resume: bump total_games (AZ terminus) so the resumed run has
    # game budget to advance past existing ckpt steps. Without the
    # bump, resume from a mid-run ckpt has the original game budget
    # already consumed → resumed run may write 0 new ckpts → flaky.
    # Mirrors DMC / BC / PPO / CFR pattern (4 fixed-budget paradigms
    # all bump terminus on resume).
    new_ckpts = resume_and_continue(
        ckpts[0],
        extra_overrides=['paradigm.az.total_games=50'],
    )
    assert len(new_ckpts) > len(ckpts), (
        f'expected new ckpt(s) after resume from {ckpts[0].name}, got {len(ckpts)} → {len(new_ckpts)} files'
    )
