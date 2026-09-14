"""CFR smoke-only stub buffer — used solely by test_cfr_smoke_full.

OpenSpec ref: ``openspec/changes/archive/cfr-driver-buffer-multihead-fix/``
ADD invariant paradigm-cfr/spec.md C6.4 — stub buffer allowed in
frozen-research tier when ``cfg.debug.cfr_smoke_stub_buffer=true`` set
(post 2026-05-24 GICG_CFR_SMOKE_STUB_BUFFER env var 砍 — cfg-driven only,
configs/cfr/smoke{,_full}.toml [debug] section)。

Production CFR (``_CFRBufferBundle``) is untouched. This module is only
imported lazily by ``CFRParadigm.make_buffer`` when the cfg flag is set,
which only the smoke CFR cfgs do。

Purpose: bridge generic ``training.core.pipeline.run_pipeline``'s
single-head ``buffer.sample(batch_size)`` contract to CFR — production
``_CFRBufferBundle.sample()`` raises because CFR is 3-headed
(advantage[player0/player1] + strategy + value), and a real fix requires
either driver multi-head protocol (~150 LOC core + 4 paradigm adapt) or
a CFR-local driver (~300 LOC). For smoke infra coverage, this stub
satisfies the Buffer protocol with a minimal valid ``Batch`` payload so
the driver path (collect → sample → loss → backward → optimizer.step →
ckpt save / resume) is exercised without claiming real CFR training.

Stub semantics:

- ``__len__`` always returns capacity (driver's
  ``len(buffer) < plan.batch_size`` guard always passes → always samples)
- ``sample`` returns ``Batch`` with CFRLoss ``REQUIRED_KEYS``
  (head / pred / target / legal_mask). ``pred`` is leaf tensor with
  ``requires_grad=True`` so ``loss.backward()`` succeeds (loss = 0,
  grad propagates to leaf only); ``clip_grad_norm_(network.parameters())``
  returns 0 because network params have no grad (CFRLoss ``del network``
  → no graph touches network in stub mode); ``optimizer.step()`` skips
  grad-None params silently.
- Head alternates advantage/strategy per call to exercise both
  CFRLoss branches.
- ``push`` accepts CollectorOutput (CFR collector still runs but stub
  ignores ingest into real reservoirs).
- ``state_dict`` / ``load_state_dict`` are trivial (ckpt path stores
  only ``net + optimizer + state``; buffer state is unused by
  CheckpointManager per current schema).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import torch

from training.core.protocols import Batch, CollectorOutput


class _SmokeStubBuffer:
    """Smoke-only stub satisfying generic Buffer protocol for CFR.

    NOT for production — guard via env flag in
    ``CFRParadigm.make_buffer``.
    """

    def __init__(self, max_actions: int = 16, capacity: int = 1000) -> None:
        self.capacity = capacity
        self.max_actions = max_actions
        # Always "full" so driver's len-check guard always passes.
        self._fake_size = capacity
        self._sample_call_count = 0

    def __len__(self) -> int:
        return self._fake_size

    def push(self, batch: CollectorOutput) -> None:
        """No-op: CFR collector still runs but stub ignores reservoir ingest."""
        del batch

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        """Return Batch with CFRLoss-compatible minimal payload.

        Alternates head=advantage/strategy per call to cover both
        CFRLoss branches. Pred is leaf tensor with requires_grad=True
        so backward succeeds; loss=0, grad propagation goes nowhere
        useful (CFRLoss ``del network``) but driver path runs to
        completion.
        """
        del rng  # stub is deterministic by design
        head = 'advantage' if (self._sample_call_count % 2 == 0) else 'strategy'
        self._sample_call_count += 1
        pred = torch.zeros(batch_size, self.max_actions, requires_grad=True)
        target = torch.zeros(batch_size, self.max_actions)
        legal_mask = torch.ones(batch_size, self.max_actions, dtype=torch.bool)
        return Batch(
            data={
                'head': head,
                'pred': pred,
                'target': target,
                'legal_mask': legal_mask,
            },
            weights=None,
            size=batch_size,
        )

    def clear(self) -> None:
        """No-op: stub has no internal storage."""
        pass

    def state_dict(self) -> dict:
        return {'stub': True, 'fake_size': self._fake_size, 'sample_count': self._sample_call_count}

    def load_state_dict(self, sd: dict) -> None:
        # Stub is stateless; ignore loaded state (smoke resume is
        # functional-only per SF-102, not bit-identical).
        del sd
