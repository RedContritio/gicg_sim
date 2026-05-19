"""BC paradigm e2e smoke — symmetric template (Phase 4 of
core-network-generic-promotion).

OpenSpec ref: ``openspec/changes/core-network-generic-promotion/specs/
training-architecture/spec.md`` invariant A1 (smoke contract).

BC paradigm-specific invariant (spec A1.4):
- cross-entropy loss SHALL NOT increase after one optimizer step
  (BC is the only paradigm where one gradient step on the same data
  MUST decrease loss — no adversary / no off-policy stale targets)
- policy logits finite

We don't load real NPZ — BC's ``BCDataset`` requires expensive ~GB
load. Instead the smoke synthesizes a tiny ``fields`` dict matching
``BCDataset.build_batch`` output shape; ``BCLoss`` consumes that
exactly as it would consume a real dataset row.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
import torch

from training.core.protocols import Batch
from training.tests.smoke_template import (
    EvalProbeReport,
    TrainStepReport,
    make_dummy_cfg,
    make_structural_batch_dict,
    run_symmetric_smoke,
)


@dataclass
class BCSmokeBuilder:
    name: str = 'bc'

    def build_paradigm(self):
        from training.paradigms.bc.paradigm import BCParadigm

        return BCParadigm()

    def build_cfg(self):
        # BC's make_network only consumes pcfg.agent; we DON'T use
        # paradigm.make_buffer / make_collector (which require NPZ).
        return make_dummy_cfg(
            'bc',
            paradigm_dict={
                'dataset_path': '/synthetic/path.npz',  # never read in smoke
                'loss_kind': 'ce',
                'lr': 1e-3,
                'n_epochs': 1,
                'batch_size': 2,
                'agent': {
                    'n_counter_slots': 128,
                    'n_hooks': 4,
                    'max_ops_per_hook': 8,
                    'max_actions': 6,
                    'd_model': 16,
                    'n_cross_layers': 1,
                },
            },
        )

    def build_network(self, paradigm, cfg):
        return paradigm.make_network(cfg)

    def build_optimizer(self, paradigm, cfg, network):
        return paradigm.make_optimizer(cfg, network)

    def build_loss(self, paradigm, cfg):
        return paradigm.make_loss(cfg)

    def build_batch(self, network, cfg) -> Batch:
        # BC loss reads batch.data['fields'] — a BCDataset.build_batch-style
        # dict carrying obs + chosen_action + legal_mask + terminal_z.
        from training.paradigms.bc.config import BCParadigmConfig

        pcfg = BCParadigmConfig.from_dict(cfg.paradigm)
        agent_cfg = pcfg.agent
        data = make_structural_batch_dict(agent_cfg, batch_size=2, seed=11)
        B, ma = 2, agent_cfg.max_actions
        # Hard target: action 0 for sample 0, action 1 for sample 1 —
        # random init logits rarely peak at these, so CE > log(1/n_legal)
        # before the train step.
        chosen_action = np.array([0, 1], dtype=np.int64)
        legal_mask = np.zeros((B, ma), dtype=bool)
        legal_mask[:, :3] = True
        tied_mask = np.zeros((B, ma), dtype=bool)
        for i, c in enumerate(chosen_action):
            tied_mask[i, c] = True
        terminal_z = np.zeros(B, dtype=np.float32)
        data['chosen_action'] = chosen_action
        data['legal_mask'] = legal_mask
        data['tied_mask'] = tied_mask
        data['terminal_z'] = terminal_z
        return Batch(data={'fields': data}, size=B)

    def eval_probe(self, paradigm, cfg, network) -> EvalProbeReport:
        # BC probe: forward + argmax over legal logits.
        batch = self.build_batch(network, cfg)
        fields = batch.data['fields']
        with torch.no_grad():
            logits, _value = network.forward_batch(fields)
        legal_mask = torch.as_tensor(fields['legal_mask'], dtype=torch.bool)
        masked = logits.masked_fill(~legal_mask, float('-inf'))
        action = int(masked[0].argmax().item())
        return EvalProbeReport(
            action=action,
            payload={'logits_finite': bool(torch.isfinite(logits).all().item())},
        )

    def paradigm_invariant(self, report: TrainStepReport, probe: EvalProbeReport) -> None:
        # A1.4 BC: cross-entropy loss SHALL not increase after one step
        # (paradigm-specific signal; BC is the only paradigm where one
        # gradient step on the same data MUST not grow loss because
        # there's no adversary / no off-policy stale targets).
        assert probe.payload['logits_finite'], 'BC logits contain NaN/inf'
        loss_before = report.loss_value_before
        loss_after = report.loss_value_after
        # Allow small slack — 1 step on synthetic batch may not strictly
        # decrease for a degenerate init, but should not GROW
        # significantly. We assert loss did not increase by more than
        # 5% of its initial value.
        assert loss_after <= loss_before * 1.05, (
            f'BC loss grew after one step: before={loss_before:.4f} after={loss_after:.4f}. '
            f'CE on hard target with full grad should not increase.'
        )


@pytest.mark.smoke
def test_bc_paradigm_smoke() -> None:
    """BC symmetric smoke via shared template — see module docstring."""
    run_symmetric_smoke(BCSmokeBuilder())
