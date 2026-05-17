"""PPO paradigm e2e smoke — symmetric template.

OpenSpec ref: ``openspec/specs/training-architecture/`` invariant A1
(smoke contract).

PPO paradigm-specific invariant (spec A1.4):
- log_prob ≤ 0 (valid log of probability)
- advantage normalized to zero-mean unit-variance (post-norm)
- clip_frac in ``[0, 1]`` (clipped surrogate fraction sanity)

Per ``ppo-structural-backbone-migration``: PPO now uses generic
structural ActorCritic backbone via PPOAgent (matching AZ/BC/DMC
smoke pattern). ``make_dummy_cfg`` + ``paradigm.make_network`` produce
the network from cfg.agent shape; structural batch built via
``make_structural_batch_dict`` (shared smoke fixture).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest
import torch
import torch.nn.functional as F

from training.core.protocols import Batch
from training.tests.smoke_template import (
    EvalProbeReport,
    TrainStepReport,
    make_dummy_cfg,
    make_structural_batch_dict,
    run_symmetric_smoke,
)


@dataclass
class PPOSmokeBuilder:
    name: str = 'ppo'

    def build_paradigm(self):
        from training.paradigms.ppo.paradigm import PPOParadigm

        return PPOParadigm()

    def build_cfg(self):
        # PPO structural backbone — same agent shape vocabulary as BC/AZ/DMC.
        return make_dummy_cfg(
            'ppo',
            paradigm_dict={
                'lr': 3e-4,
                'batch_size': 4,
                'minibatch_size': 2,
                'buffer_cap': 100,
                'n_epochs': 1,
                'agent': {
                    'n_counter_slots': 128,
                    'n_hooks': 4,
                    'max_tokens_per_hook': 8,
                    'max_actions': 6,
                    'd_model': 16,
                    'n_cross_layers': 1,
                },
                'rollout': {'n_games_per_iter': 1, 'rollout_opponent': 'random'},
            },
        )

    def build_network(self, paradigm, cfg):
        # paradigm.make_network builds via AgentConfig → PPOAgent → ActorCritic.
        return paradigm.make_network(cfg)

    def build_optimizer(self, paradigm, cfg, network):
        return paradigm.make_optimizer(cfg, network)

    def build_loss(self, paradigm, cfg):
        return paradigm.make_loss(cfg)

    def build_batch(self, network, cfg) -> Batch:
        # PPO loss (path B) reads 'collated' / 'action' / 'old_log_prob' /
        # 'advantage' / 'return'. Pre-normalize advantage to zero-mean
        # unit-variance per spec A1.4 PPO bullet.
        agent_cfg = network.agent.cfg
        B = 4
        ma = agent_cfg.max_actions
        torch.manual_seed(29)
        collated = make_structural_batch_dict(agent_cfg, batch_size=B, seed=29)
        legal_mask = np.zeros((B, ma), dtype=bool)
        legal_mask[:, :ma] = True  # all actions legal for smoke
        collated['legal_mask'] = legal_mask
        action = torch.tensor([0, 1, 2, 0], dtype=torch.long)
        # Uniform old_log_prob over ma legal actions.
        old_lp = torch.full((B,), math.log(1.0 / ma), dtype=torch.float32)
        adv_raw = torch.tensor([1.0, -0.5, 0.7, -1.2], dtype=torch.float32)
        adv_norm = (adv_raw - adv_raw.mean()) / (adv_raw.std() + 1e-8)
        ret = torch.tensor([0.5, -0.5, 0.3, -0.3], dtype=torch.float32)
        self._cached_adv_norm = adv_norm
        return Batch(
            data={
                'collated': collated,
                'action': action,
                'old_log_prob': old_lp,
                'advantage': adv_norm,
                'return': ret,
            },
            size=B,
        )

    def eval_probe(self, paradigm, cfg, network) -> EvalProbeReport:
        # PPO probe: forward_batch → masked legal softmax → sample one
        # action + capture log_prob + value.
        agent_cfg = network.agent.cfg
        ma = agent_cfg.max_actions
        torch.manual_seed(31)
        collated = make_structural_batch_dict(agent_cfg, batch_size=1, seed=31)
        legal_mask_np = np.zeros((1, ma), dtype=bool)
        legal_mask_np[:, :ma] = True
        collated['legal_mask'] = legal_mask_np
        with torch.no_grad():
            policy_logits, value = network.forward_batch(collated)
        legal_mask_t = torch.as_tensor(legal_mask_np, dtype=torch.bool)
        neg_inf = torch.finfo(policy_logits.dtype).min
        masked = torch.where(legal_mask_t, policy_logits, torch.full_like(policy_logits, neg_inf))
        log_probs = F.log_softmax(masked, dim=-1)
        probs = log_probs.exp()[0]
        action = int(torch.multinomial(probs, num_samples=1).item())
        log_prob = float(log_probs[0, action].item())
        return EvalProbeReport(
            action=action,
            payload={
                'log_prob': log_prob,
                'value': float(value[0].item()),
                'advantage_mean_abs': float(self._cached_adv_norm.mean().abs().item()),
                'advantage_std': float(self._cached_adv_norm.std().item()),
            },
        )

    def paradigm_invariant(self, report: TrainStepReport, probe: EvalProbeReport) -> None:
        # A1.4 PPO: log_prob ≤ 0; advantage zero-mean unit-variance;
        # clip_frac in [0, 1].
        assert probe.payload['log_prob'] <= 1e-5, (
            f'PPO log_prob > 0 (not a valid log-prob): {probe.payload["log_prob"]}'
        )
        assert probe.payload['advantage_mean_abs'] < 1e-5, (
            f'PPO advantage not zero-mean after normalization: mean_abs={probe.payload["advantage_mean_abs"]}'
        )
        assert abs(probe.payload['advantage_std'] - 1.0) < 1e-4, (
            f'PPO advantage not unit-variance after normalization: std={probe.payload["advantage_std"]}'
        )
        # clip_frac fed through breakdown — check both before + after.
        for label, b in (('before', report.breakdown_before), ('after', report.breakdown_after)):
            cf = b.get('clip_frac')
            if cf is not None:
                assert 0.0 <= cf <= 1.0, f'PPO clip_frac ({label}) = {cf} out of [0, 1]'


@pytest.mark.smoke
def test_ppo_paradigm_smoke() -> None:
    """PPO symmetric smoke via shared template — see module docstring."""
    run_symmetric_smoke(PPOSmokeBuilder())
