"""DMC paradigm e2e smoke — symmetric template (Phase 4 of
core-network-generic-promotion).

OpenSpec ref: ``openspec/specs/training-architecture/smoke-contract.md``.

DMC paradigm-specific invariant (spec A1.4):
- Q-value finite (no NaN/inf from the Q head)
- ε=1 ε-greedy actor SHALL explore every step (guards the random branch
  against accidentally falling through to argmax)
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
class DMCSmokeBuilder:
    name: str = 'dmc'

    def build_paradigm(self):
        from training.paradigms.dmc.paradigm import DMCParadigm

        return DMCParadigm()

    def build_cfg(self):
        return make_dummy_cfg(
            'dmc',
            paradigm_dict={
                'lr': 1e-3,
                'batch_size': 2,
                'buffer_cap': 100,
                'epsilon': 0.05,
                'agent': {
                    'n_counter_slots': 128,
                    'n_hooks': 4,
                    'max_ops_per_hook': 8,
                    'max_actions': 6,
                    'd_model': 16,
                    'n_cross_layers': 1,
                },
                # Default opponent_mix (sums to 1.0).
            },
        )

    def build_network(self, paradigm, cfg):
        return paradigm.make_network(cfg)

    def build_optimizer(self, paradigm, cfg, network):
        return paradigm.make_optimizer(cfg, network)

    def build_loss(self, paradigm, cfg):
        return paradigm.make_loss(cfg)

    def build_batch(self, network, cfg) -> Batch:
        # DMC loss reads collated obs dict + action_idx + returns.
        from training.paradigms.dmc.config import DMCParadigmConfig

        pcfg = DMCParadigmConfig.from_dict(cfg.paradigm)
        agent_cfg = pcfg.agent
        data = make_structural_batch_dict(agent_cfg, batch_size=2, seed=13)
        action_idx = torch.tensor([0, 1], dtype=torch.long)
        returns = torch.tensor([1.0, -1.0], dtype=torch.float32)
        return Batch(
            data={'collated': data, 'action_idx': action_idx, 'returns': returns},
            size=2,
        )

    def eval_probe(self, paradigm, cfg, network) -> EvalProbeReport:
        # DMC probe: forward → take logit at action 0 as Q-value.
        from training.paradigms.dmc.config import DMCParadigmConfig
        from training.paradigms.dmc.policy import DMCEpisodePolicy

        pcfg = DMCParadigmConfig.from_dict(cfg.paradigm)
        agent_cfg = pcfg.agent
        obs_dict = make_structural_batch_dict(agent_cfg, batch_size=1, seed=17)
        with torch.no_grad():
            q_logits, _, _ = network.forward_batch(obs_dict)
        q_value = float(q_logits[0, 0].item())
        # ε=1 explore branch: episode policy SHOULD pick random for every
        # step. We use a stub provider so we don't need a real env.
        eps1_policy = DMCEpisodePolicy(epsilon=1.0, seed=42, deterministic=False)

        class _StubProvider:
            def forward(self, obs, mask):
                return {'logit_as_q': torch.zeros(4)}

            def update_weights(self, **kw):
                return 0

            def current_version(self):
                return 0

            def close(self):
                pass

        mask = np.array([True, True, True, True])
        actions = []
        for _ in range(20):
            _a, meta = eps1_policy.act(obs=None, mask=mask, provider=_StubProvider())
            actions.append(meta.get('explore', False))
        explored = sum(1 for e in actions if e)
        return EvalProbeReport(
            action=0,
            payload={
                'q_value': q_value,
                'q_finite': bool(np.isfinite(q_value)),
                'eps1_explore_count': explored,
                'eps1_total': 20,
            },
        )

    def paradigm_invariant(self, report: TrainStepReport, probe: EvalProbeReport) -> None:
        # A1.4 DMC: Q-value finite; ε=1 → all random.
        assert probe.payload['q_finite'], f'DMC Q-value not finite: {probe.payload["q_value"]}'
        assert probe.payload['eps1_explore_count'] == probe.payload['eps1_total'], (
            f'DMC ε=1 must explore every step, got {probe.payload["eps1_explore_count"]}/{probe.payload["eps1_total"]}'
        )


@pytest.mark.smoke
def test_dmc_paradigm_smoke() -> None:
    """DMC symmetric smoke via shared template — see module docstring."""
    run_symmetric_smoke(DMCSmokeBuilder())
