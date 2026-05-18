"""CFR paradigm smoke_full — full driver e2e + ckpt save/load (A1.6).

OpenSpec ref: ``openspec/changes/paradigm-smoke-full-tier/specs/
training-architecture/spec.md`` invariant A1.6 + DECISIONS SF-105
+ ``openspec/changes/cfr-driver-buffer-multihead-fix/`` (stub buffer).

CFR has a 3-headed buffer (advantage[player0/player1] + strategy +
value) — ``_CFRBufferBundle.sample()`` raises because the generic
``training/core/pipeline.py::run_pipeline`` calls
``buffer.sample(batch_size)`` (single-head Buffer protocol).

Per cfr-driver-buffer-multihead-fix C6.4 ADD, this test injects a
smoke-only stub buffer via env flag ``GICG_CFR_SMOKE_STUB_BUFFER=1``.
The stub satisfies the generic Buffer protocol with a minimal valid
``Batch`` payload (CFRLoss REQUIRED_KEYS) so the driver path runs
end-to-end:

    collect → sample → loss → backward → optimizer.step → ckpt save → resume

This does NOT validate CFR training quality (CFR remains frozen-research
tier per C6.1 + C6.3). Production CFR runs are unaffected — env flag is
test-only and dispatch in ``CFRParadigm.make_buffer`` keeps
``_CFRBufferBundle`` as the production default.

T-25 rewrite note: pre-T-23 driver had ``--max-steps`` which capped
the initial run at step 30 so resume from ckpt_10 had room to advance
to n_iterations=50. Spec C-1 deleted ``--max-steps``; we now cap via
cfg's ``n_iterations=50`` and bump on resume to ``n_iterations=80``
(matching BC / PPO terminus-bump pattern) so post-resume ckpts at
step 60 / 70 / 80 appear as new files.
"""

from __future__ import annotations

import pytest

from training.tests.smoke_full_template import (
    REPO_ROOT,
    resume_and_continue,
    run_paradigm_train_via_driver,
    verify_ckpt_files,
)

_STUB_BUFFER_ENV = {'GICG_CFR_SMOKE_STUB_BUFFER': '1'}


@pytest.mark.smoke_full
def test_cfr_smoke_full(tmp_path) -> None:
    """CFR full smoke — driver train (50 iter) + ckpt save + resume.

    Stub buffer injected via env flag per cfr-driver-buffer-multihead-fix
    C6.4 — production CFR unaffected.
    """
    cfg = REPO_ROOT / 'configs' / 'cfr' / 'smoke_full.toml'
    assert cfg.exists(), f'cfg missing: {cfg}'

    artifacts = run_paradigm_train_via_driver(cfg, tmp_path, extra_env=_STUB_BUFFER_ENV)
    ckpts = verify_ckpt_files(artifacts, expected_min_count=2)

    # Bump n_iterations to give the resumed run room for new ckpt(s).
    # Initial run reaches step 50 (n_iterations=50, save_every=10 →
    # ckpts at 10/20/30/40/50); resume from earliest ckpt_10 + bump
    # n_iterations=80 → continues 10 → 80 → adds ckpts at 60/70/80.
    new_ckpts = resume_and_continue(
        ckpts[0],
        extra_env=_STUB_BUFFER_ENV,
        extra_overrides=['paradigm.cfr.n_iterations=80'],
    )
    assert len(new_ckpts) > len(ckpts), (
        f'expected new ckpt(s) after resume from {ckpts[0].name}, got {len(ckpts)} → {len(new_ckpts)} files'
    )


def test_smoke_stub_buffer_satisfies_protocol() -> None:
    """T2.4 — stub satisfies generic Buffer protocol (runtime_checkable).

    Catches future Buffer protocol changes — if a SHALL method is added
    to ``training.core.protocols.Buffer``, this assertion will fail and
    flag the stub for update.
    """
    from training.core.protocols import Buffer
    from training.tests._cfr_smoke_stub import _SmokeStubBuffer

    stub = _SmokeStubBuffer(max_actions=8, capacity=100)
    assert isinstance(stub, Buffer), (
        'stub no longer satisfies generic Buffer protocol — sync stub with protocol changes'
    )
