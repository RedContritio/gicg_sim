"""PPO paradigm smoke_full — full driver e2e + ckpt save/load (A1.6).

OpenSpec ref: ``openspec/specs/training-architecture/smoke-contract.md``
+ DECISIONS SF-105.

STATUS (post 2026-05-17 cascade closure):

1. ``ppo-rollout-card-pool-none-fix`` (archived, commit b5c8f4e) —
   fixed 3 处 ``list(getattr(scen, X, ())) or Y`` broken patterns
   (``_rollout.py:130-131`` card_pool/obs_mask + ``_async.py:59``)
2. ``ppo-buffer-clear-orchestration`` (archived, commit 91a6b68) — wired
   pipeline driver post-train ``buffer.clear()`` for PPO on-policy P4.1
   via ``StepPlan.clear_buffer_after_train: bool`` flag。
3. ``az-resume-shape-fix`` (archived, commit f2e18f3) — fixed shared
   root cause(``actor_critic.py:258`` ``sorted(head_kinds)`` for
   deterministic ModuleDict iteration order across process)which
   ALSO unblocked PPO smoke_full(同 multi-head set iteration bug)。

5/5 paradigm smoke_full now PASS。
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
def test_ppo_smoke_full(tmp_path) -> None:
    """PPO full smoke — driver train (≥ 100 step) + ckpt save + resume."""
    cfg = REPO_ROOT / 'configs' / 'ppo' / 'smoke_full.toml'
    assert cfg.exists(), f'cfg missing: {cfg}'

    artifacts = run_paradigm_train_via_driver(cfg, tmp_path)
    ckpts = verify_ckpt_files(artifacts, expected_min_count=2)

    # Resume from latest ckpt + bump terminus so new ckpt files appear at
    # post-terminus steps (BC pattern: same fixed-terminus paradigm).
    new_ckpts = resume_and_continue(
        ckpts[-1],
        extra_overrides=['paradigm.ppo.total_iterations=80'],
    )
    old_steps = {int(p.stem.split('_')[1]) for p in ckpts}
    new_steps = {int(p.stem.split('_')[1]) for p in new_ckpts}
    assert max(new_steps) > max(old_steps), 'resume must advance beyond the prior final checkpoint'
