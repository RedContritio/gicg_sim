"""AZ paradigm e2e smoke — symmetric template (Phase 4 of
core-network-generic-promotion).

OpenSpec ref: ``openspec/changes/core-network-generic-promotion/specs/
training-architecture/spec.md`` invariant A1 (smoke contract).

This file is ONE of 5 paradigm smoke files; the contract / lifecycle
is owned by ``training.tests.smoke_template.run_symmetric_smoke``.
Each paradigm's smoke file supplies a ``SmokeBuilder`` and calls the
shared template — adding a 6th paradigm = registering one more file
in the same shape.

AZ paradigm-specific invariant (spec A1.4):
- value head output in ``[-1, 1]`` (tanh-bounded)
- policy logits + value finite
- prior over legal actions sums to 1
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
class AZSmokeBuilder:
    name: str = 'az'

    def build_paradigm(self):
        from training.paradigms.az import AZParadigm

        return AZParadigm()

    def build_cfg(self):
        # Tiny dims so MCTS / forward cost is minimal. n_counter_slots
        # SHALL be >= N_STRUCTURAL (66) — struct_readout requires it.
        return make_dummy_cfg(
            'az',
            paradigm_dict={
                'lr': 1e-3,
                'batch_size': 2,
                'buffer_cap': 50,
                'agent': {
                    'n_counter_slots': 128,
                    'n_hooks': 4,
                    'max_ops_per_hook': 8,
                    'max_actions': 6,
                    'd_model': 16,
                    'n_cross_layers': 1,
                },
                'mcts': {'n_rollouts': 2, 'profile': False},
                'train': {'l2_coef': 0.0, 'entropy_coef': 0.0, 'delta_aux_coef': 0.0},
            },
        )

    def build_network(self, paradigm, cfg):
        return paradigm.make_network(cfg)

    def build_optimizer(self, paradigm, cfg, network):
        return paradigm.make_optimizer(cfg, network)

    def build_loss(self, paradigm, cfg):
        return paradigm.make_loss(cfg)

    def build_batch(self, network, cfg) -> Batch:
        # AZ loss takes pi_target + z_target + legal_mask on top of the
        # structural obs dict — forward_batch consumes the full obs.
        from training.paradigms.az.config import AZParadigmConfig

        pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
        agent_cfg = pcfg.agent
        data = make_structural_batch_dict(agent_cfg, batch_size=2, seed=7)
        B, ma = 2, agent_cfg.max_actions
        # Uniform pi_target over 2 legal actions (spec A2.2 expected shape).
        pi_target = np.zeros((B, ma), dtype=np.float32)
        pi_target[:, :2] = 0.5
        z_target = np.array([1.0, -1.0], dtype=np.float32)
        legal_mask = np.zeros((B, ma), dtype=bool)
        legal_mask[:, :2] = True
        data['pi_target'] = pi_target
        data['z_target'] = z_target
        data['legal_mask'] = legal_mask
        return Batch(data=data, size=B)

    def eval_probe(self, paradigm, cfg, network) -> EvalProbeReport:
        # AZ probe: forward through value head + argmax over policy logits.
        # Network.forward_batch returns (logits, value, delta_pred). We
        # reuse the build_batch obs as the probe input.
        batch = self.build_batch(network, cfg)
        with torch.no_grad():
            logits, value, _delta = network.forward_batch(batch.data)
        legal_mask = torch.as_tensor(batch.data['legal_mask'], dtype=torch.bool)
        masked = logits.masked_fill(~legal_mask, float('-inf'))
        action = int(masked[0].argmax().item())
        return EvalProbeReport(
            action=action,
            payload={
                'value_min': float(value.min().item()),
                'value_max': float(value.max().item()),
                'logits_finite': bool(torch.isfinite(logits).all().item()),
                'prior_sum': float(torch.softmax(masked[0, :2], dim=-1).sum().item()),
            },
        )

    def paradigm_invariant(self, report: TrainStepReport, probe: EvalProbeReport) -> None:
        # A1.4 AZ: value ∈ [-1, 1]; logits + value finite.
        assert probe.payload['logits_finite'], 'AZ policy logits contain NaN/inf'
        assert -1.0 <= probe.payload['value_min'] <= 1.0, (
            f'AZ value_min={probe.payload["value_min"]} out of [-1, 1] (tanh-bounded head)'
        )
        assert -1.0 <= probe.payload['value_max'] <= 1.0, f'AZ value_max={probe.payload["value_max"]} out of [-1, 1]'
        assert abs(probe.payload['prior_sum'] - 1.0) < 1e-4, (
            f'AZ prior over 2 legal actions must sum to 1, got {probe.payload["prior_sum"]}'
        )
        # Sanity: loss did NOT explode after the step.
        assert abs(report.loss_value_after) < 100.0


@pytest.mark.smoke
def test_az_paradigm_smoke() -> None:
    """AZ symmetric smoke via shared template — see module docstring."""
    run_symmetric_smoke(AZSmokeBuilder())
