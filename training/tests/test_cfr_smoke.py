"""CFR paradigm e2e smoke — symmetric template (Phase 4 of
core-network-generic-promotion).

OpenSpec ref: ``openspec/changes/core-network-generic-promotion/specs/
training-architecture/spec.md`` invariant A1 (smoke contract).

CFR paradigm-specific invariant (spec A1.4):
- strategy distribution sums to 1 over legal actions (avg_policy head
  output after softmax + legal mask)
- advantage loss (regret) finite

CFR's network topology differs from AZ / BC / DMC: it uses its own
``_CFRTrunk`` (not the generic ``ActorCritic``), so the forward call
signature is shorter (12 args, no typed-damage segments). We pre-
forward through the advantage head + supply the predicted regret as
``batch.data['pred']`` per ``CFRLoss``'s forward-free contract.
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
    make_tiny_agent_cfg,
    run_symmetric_smoke,
)


def _forward_cfr(cfr_module, obs_dict) -> torch.Tensor:
    """Forward through CFR AdvantageNet or CFRStrategyNet's policy head.

    Both expose the same 12-arg forward signature (no typed segments —
    CFR's ``_CFRTrunk`` doesn't consume recent_damage / prepare_skill /
    modifier_log). Returns:
    - For ``AdvantageNet``: regret tensor (B, max_actions)
    - For ``CFRStrategyNet``: logits tensor (first elem of (logits, value))
    """
    from training.core.structural import (
        compute_structural_obspos,
        compute_structural_values,
    )

    def _t(k, dt):
        v = obs_dict[k]
        if isinstance(v, torch.Tensor):
            return v.to(dt)
        return torch.as_tensor(v, dtype=dt)

    counter_values = _t('counter_values', torch.float32)
    counter_sids = _t('counter_sids', torch.long)
    active_slot_mask = _t('active_slot_mask', torch.bool)
    hook_types = _t('hook_types', torch.long)
    hook_values = _t('hook_values', torch.float32)
    hook_mask = _t('hook_mask', torch.bool)
    card_buckets = _t('card_buckets', torch.float32)
    enemy_sizes = _t('enemy_sizes', torch.float32)
    meta = _t('meta', torch.float32)
    action_refs = _t('action_refs', torch.long)
    action_payments = _t('action_payments', torch.float32)
    char_skill_refs = _t('char_skill_refs', torch.long)

    hook_encoder = cfr_module.hook_encoder if hasattr(cfr_module, 'hook_encoder') else cfr_module.trunk.hook_encoder
    hook_emb = hook_encoder(hook_types, hook_values, hook_mask)
    structural_obspos = compute_structural_obspos(counter_sids, active_slot_mask)
    structural_values = compute_structural_values(counter_values, structural_obspos)
    out = cfr_module(
        counter_values,
        counter_sids,
        active_slot_mask,
        hook_emb,
        hook_mask,
        card_buckets,
        enemy_sizes,
        meta,
        action_refs,
        action_payments,
        structural_values,
        char_skill_refs,
    )
    if isinstance(out, tuple):
        return out[0]
    return out


@dataclass
class CFRSmokeBuilder:
    name: str = 'cfr'

    def build_paradigm(self):
        from training.paradigms.cfr.paradigm import CFRParadigm

        return CFRParadigm()

    def build_cfg(self):
        return make_dummy_cfg(
            'cfr',
            paradigm_dict={
                'strategy_lr': 1e-3,
                'advantage_lr': 1e-3,
                'fit_batch_size': 2,
                'agent': {
                    'n_counter_slots': 128,
                    'n_hooks': 4,
                    'max_tokens_per_hook': 8,
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
        # CFR loss is forward-free (driver pre-forwards). We pre-forward
        # the advantage net so backward updates real params.
        ma = 6
        B = 2
        agent_cfg = make_tiny_agent_cfg(max_actions=ma, n_counter_slots=128)
        obs_dict = make_structural_batch_dict(agent_cfg, batch_size=B, seed=19)
        adv_net = network.advantage_head(0)
        pred = _forward_cfr(adv_net, obs_dict)  # (B, ma)
        target = torch.zeros(B, ma)
        legal_mask = torch.ones(B, ma, dtype=torch.bool)
        return Batch(
            data={'head': 'advantage', 'pred': pred, 'target': target, 'legal_mask': legal_mask},
            size=B,
        )

    def eval_probe(self, paradigm, cfg, network) -> EvalProbeReport:
        # CFR probe: avg_policy head (strategy_net) produces the
        # production-eval distribution. Verify sums-to-1 over legal.
        ma = 6
        agent_cfg = make_tiny_agent_cfg(max_actions=ma, n_counter_slots=128)
        obs_dict = make_structural_batch_dict(agent_cfg, batch_size=1, seed=23)
        with torch.no_grad():
            logits = _forward_cfr(network.strategy_net, obs_dict)
        legal_mask = torch.ones(1, ma, dtype=torch.bool)
        masked = logits.masked_fill(~legal_mask, float('-inf'))
        strategy = torch.softmax(masked, dim=-1)
        return EvalProbeReport(
            action=int(strategy[0].argmax().item()),
            payload={
                'strategy_sum': float(strategy[0].sum().item()),
                'logits_finite': bool(torch.isfinite(logits).all().item()),
            },
        )

    def paradigm_invariant(self, report: TrainStepReport, probe: EvalProbeReport) -> None:
        # A1.4 CFR: strategy distribution sums to 1 over legal actions;
        # regret (advantage loss) finite.
        assert probe.payload['logits_finite'], 'CFR strategy logits contain NaN/inf'
        assert abs(probe.payload['strategy_sum'] - 1.0) < 1e-4, (
            f'CFR strategy must sum to 1, got {probe.payload["strategy_sum"]}'
        )
        # Regret finite: loss after step is finite (NaN guard in
        # template already checks this; explicit per spec phrasing).
        assert np.isfinite(report.loss_value_after), f'CFR advantage loss not finite: {report.loss_value_after}'


@pytest.mark.smoke
def test_cfr_paradigm_smoke() -> None:
    """CFR symmetric smoke via shared template — see module docstring."""
    run_symmetric_smoke(CFRSmokeBuilder())
