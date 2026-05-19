"""Phase 4 end-to-end smoke: r009 ckpt load via core/matchup/loaders.py adapter path.

Per AZ Phase 4 task brief (openspec/changes/az-paradigm-rewrite/tasks.md T4) + user
reframe (2026-05-16): verify the **codepath** end-to-end through the updated adapter
(T3a switched ``core/matchup/loaders.py`` to import ``Agent`` from
``training.paradigms.az.network``), NOT strict numerical regression.

Why path smoke instead of strict regression:

- r009 ckpt (April 2026) predates ADR-0019 §B.3a TypedDamageEncoder addition
  (2026-05-08, memory: ``project_typed_obs_ckpt_break``). The schema is
  intrinsically broken vs current ``ActorCritic`` — strict load will fail
  regardless of which Agent path (legacy or adapter) is used.

- δ commit ``b5ee49b`` (T2.6) already established **parity** between inline Agent
  and legacy Agent for r009 ckpt load behavior (key sets identical, load errors
  identical). That gates the Phase 2 inline.

- This Phase 4 test extends the gate one layer higher: verify the full
  ``loaders.py`` → adapter ``Agent`` → ``ActorCritic.load_state_dict`` codepath
  resolves and fails with EXACTLY the known ADR-0019 signature (locks the
  known break — any drift would surface here as a different error class /
  message pattern).

Pass criteria:
    1. ``load_player({'type': 'az', 'ckpt': r009})`` is importable (no
       ImportError — confirms Phase 2/3 didn't miss any ref).
    2. The load fails with ``RuntimeError`` mentioning ``typed_damage_encoder``
       (the ADR-0019 missing-key signature) — confirms the failure mode is
       the expected pre-existing break, not new drift from Phase 2/3 inline.
"""

from __future__ import annotations

import os
import pathlib

import pytest
import torch

# Artifacts live in the main repo (gitignored, not replicated to worktrees).
# Resolve via ``GICG_REPO_ROOT`` env var if set, else walk up from this test
# file looking for a sibling ``artifacts/`` dir. Same pattern as the δ smoke
# (test_az_network_phase2_r009_smoke.py).
_REL = 'artifacts/202604270918_r009_bc_pretrain_stage3/epoch_3.pt'


def _resolve_r009_path() -> pathlib.Path:
    env_root = os.environ.get('GICG_REPO_ROOT')
    if env_root:
        return pathlib.Path(env_root) / _REL
    cwd = pathlib.Path.cwd().resolve()
    candidates = [cwd / _REL]
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / _REL)
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


R009_CKPT_PATH = _resolve_r009_path()


def test_loaders_module_imports_via_adapter_path():
    """Smoke 1: ``core/matchup/loaders`` imports without ImportError.

    T3a switched ``_load_agent_from_ckpt`` to ``from
    training.paradigms.az.network import Agent`` (adapter path). If Phase
    2/3 missed an inline reference, this import would fail at module load
    time. Also asserts the ``LOADERS`` registry has the ``az`` entry that
    routes through this codepath.
    """
    from training.core.matchup import loaders

    assert 'az' in loaders.LOADERS, f"loaders.LOADERS missing 'az' entry: {sorted(loaders.LOADERS)}"
    # The adapter-side Agent class must be importable too (T3a's import target).
    from training.paradigms.az.network import Agent

    assert Agent.__module__ == 'training.paradigms.az.network', (
        f'Agent module is {Agent.__module__}, expected adapter path '
        f'training.paradigms.az.network (T3a regression — production '
        f'loaders.py still routing through legacy?)'
    )


@pytest.mark.skipif(not R009_CKPT_PATH.exists(), reason=f'r009 ckpt not present at {R009_CKPT_PATH}')
def test_r009_ckpt_blob_readable():
    """Smoke 2: r009 ckpt is readable by ``torch.load`` and has the
    ``{'cfg': dict, 'net': state_dict}`` shape ``_load_agent_from_ckpt``
    expects. Pre-condition for the e2e load test below.
    """
    blob = torch.load(str(R009_CKPT_PATH), map_location='cpu', weights_only=False)
    assert isinstance(blob, dict)
    assert 'cfg' in blob
    assert 'net' in blob
    cfg = blob['cfg']
    assert isinstance(cfg, dict)
    # AgentConfig required fields — same set the loaders.py path will
    # unpack via ``AgentConfig(**blob['cfg'])``.
    for required in ('n_counter_slots', 'n_hooks', 'max_ops_per_hook', 'max_actions', 'd_model'):
        assert required in cfg, f'r009 cfg missing required key {required!r}'


@pytest.mark.skipif(not R009_CKPT_PATH.exists(), reason=f'r009 ckpt not present at {R009_CKPT_PATH}')
def test_r009_load_via_load_player_fails_with_adr0019_signature():
    """Phase 4 e2e gate: route r009 ckpt load through the production
    ``load_player({'type': 'az', ...})`` codepath. The load is expected
    to fail with EXACTLY the ADR-0019 §B.3a TypedDamageEncoder
    missing-key signature.

    Why this is a pass, not a fail:

    - r009 was trained April 2026, before ADR-0019 was decided
      (2026-05-08). Loading it into the current ``ActorCritic`` (which
      now has ``typed_damage_encoder.*`` + ``pool_norms.*`` modules)
      cannot succeed in strict mode — that's a pre-existing
      schema break, NOT a Phase 2/3 regression.

    - What this test gates: the **failure mode** is the canonical
      ADR-0019 signature (RuntimeError mentioning
      ``typed_damage_encoder``). If the adapter-path inline somehow
      introduced different drift, the failure pattern would change
      (e.g., AttributeError on Agent class API, ImportError on a stale
      ref, or shape mismatch on a NON-ADR-0019 layer) — and this test
      would catch it.
    """
    from training.core.matchup.loaders import load_player

    spec = {'type': 'az', 'ckpt': str(R009_CKPT_PATH), 'n_simulations': 0}
    with pytest.raises(RuntimeError) as exc_info:
        load_player(spec)

    err_msg = str(exc_info.value)
    assert 'typed_damage_encoder' in err_msg, (
        f'r009 load failed with NON-ADR-0019 error — possible Phase 2/3 inline drift.\n'
        f'Expected substring: "typed_damage_encoder" (ADR-0019 §B.3a marker)\n'
        f'Got: {err_msg[:600]}'
    )


@pytest.mark.skipif(not R009_CKPT_PATH.exists(), reason=f'r009 ckpt not present at {R009_CKPT_PATH}')
def test_r009_load_failure_signature_matches_adr0019_at_agent_level():
    """Sibling negative test at the ``Agent.net.load_state_dict``
    boundary (one layer below ``load_player``). Confirms the
    ADR-0019 signature is generated by the ActorCritic itself,
    not by some loader-layer wrapping/transformation.

    This locks **what is missing**: both ``typed_damage_encoder.*`` AND
    ``pool_norms.*`` modules should be reported as missing — matches
    the memory note "ADR-0019 typed obs ckpt 全失效". If only one of
    them appears, the inline ActorCritic construction has drifted from
    the legacy one.
    """
    from training.core.network import AgentConfig
    from training.paradigms.az.network import Agent

    blob = torch.load(str(R009_CKPT_PATH), map_location='cpu', weights_only=False)
    cfg = AgentConfig(**blob['cfg'])
    agent = Agent(cfg)

    # Strict-mode load surfaces missing keys in the error message.
    with pytest.raises(RuntimeError) as exc_info:
        agent.net.load_state_dict(blob['net'], strict=True)

    err_msg = str(exc_info.value)
    # Both ADR-0019 §B.3a modules must appear in the missing-keys report.
    assert 'typed_damage_encoder' in err_msg, (
        f'Expected typed_damage_encoder in missing-keys error (ADR-0019 §B.3a).\nGot: {err_msg[:600]}'
    )
    assert 'pool_norms' in err_msg, (
        f'Expected pool_norms in missing-keys error (ADR-0019 §B.3a sibling).\nGot: {err_msg[:600]}'
    )
