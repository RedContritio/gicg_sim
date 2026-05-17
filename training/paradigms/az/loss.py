"""AZLoss — KL(policy) + MSE(value) wrapped as LossComputer protocol.

Spec ref: paradigm-az/spec.md A2.1-A2.3. Reuses the legacy
``training.paradigms.az._az_losses.az_losses`` (moved out of legacy in
core-network-generic-promotion Phase 2F) so the algorithm-level
math (masked log_softmax + MSE + optional L2 + optional entropy bonus)
is unchanged.

The Batch from ``AZBuffer.sample`` carries the legacy AZ buffer dict
(counter_values / pi_target / z_target / legal_mask / etc.); the loss
runs network.forward_batch internally — driver only calls
``loss_fn.compute(network, batch)``.
"""

from __future__ import annotations

from typing import Any

import torch

from training.core.protocols import Batch, LossResult
from training.paradigms.az._az_losses import az_losses


class AZLoss:
    """LossComputer protocol implementation for AZ (A2.1)."""

    def __init__(self, paradigm_cfg: Any) -> None:
        self.cfg = paradigm_cfg
        self.train_cfg = paradigm_cfg.train if paradigm_cfg is not None else None

    def compute(self, network: Any, batch: Batch) -> LossResult:
        """Forward + KL/MSE on AZ batch.

        Args:
            network: AZNetwork (or any object exposing
                ``forward_batch(dict)`` returning (logits, value, delta_pred)
                + an ``.agent`` / ``.net`` attribute for L2).
            batch: ``Batch`` whose ``data`` carries the legacy AZ buffer
                fields: ``counter_values, counter_sids, active_slot_mask,
                hook_types, hook_values, hook_mask, card_buckets,
                enemy_sizes, meta, action_refs, action_payments,
                char_skill_refs, recent_damage, prepare_skill, modifier_log,
                pi_target, z_target, legal_mask`` (+ optional
                ``counter_target`` / ``has_counter_target`` /
                ``active_slot_mask`` for delta_aux head).
        """
        d = batch.data
        required = ('pi_target', 'z_target', 'legal_mask')
        missing = [k for k in required if k not in d]
        if missing:
            raise ValueError(f'AZLoss.compute: batch.data missing required keys {missing} (got {sorted(d.keys())})')

        if not hasattr(network, 'forward_batch'):
            raise TypeError(f'AZLoss.compute: network must expose forward_batch(dict); got {type(network).__name__}')

        # Run network forward.
        logits, value, delta_pred = network.forward_batch(d)

        # Resolve model parameter root for L2.
        model = network.net if hasattr(network, 'net') else network

        device = logits.device
        legal_mask = torch.as_tensor(d['legal_mask'], dtype=torch.bool, device=device)
        pi_target = torch.as_tensor(d['pi_target'], dtype=torch.float32, device=device)
        z_target = torch.as_tensor(d['z_target'], dtype=torch.float32, device=device)

        train_cfg = self.train_cfg
        l2_coef = train_cfg.l2_coef if train_cfg is not None else 0.0
        entropy_coef = train_cfg.entropy_coef if train_cfg is not None else 0.0

        losses = az_losses(
            logits=logits,
            value=value,
            legal_mask=legal_mask,
            pi_target=pi_target,
            z_target=z_target,
            model=model,
            l2_coef=l2_coef,
            entropy_coef=entropy_coef,
        )

        # delta_aux (counter prediction head) — only applied if both cfg
        # asks for it AND batch carries the supervision signal. Mirrors
        # train_step._select_value_target branch.
        delta_aux_coef = train_cfg.delta_aux_coef if train_cfg is not None else 0.0
        if delta_aux_coef > 0.0 and 'counter_target' in d and 'has_counter_target' in d and 'active_slot_mask' in d:
            counter_target = torch.as_tensor(d['counter_target'], dtype=torch.float32, device=device)
            has_target = torch.as_tensor(d['has_counter_target'], dtype=torch.bool, device=device)
            active_mask = torch.as_tensor(d['active_slot_mask'], dtype=torch.bool, device=device)
            row_mask = has_target.unsqueeze(-1) & active_mask
            diff2 = (delta_pred - counter_target) ** 2
            denom = row_mask.float().sum().clamp_min(1.0)
            delta_loss = (diff2 * row_mask.float()).sum() / denom
            losses['delta_aux'] = delta_loss
            losses['total'] = losses['total'] + delta_aux_coef * delta_loss

        breakdown = {
            'loss': float(losses['total'].detach().item()),
            'policy_loss': float(losses['policy'].detach().item()),
            'value_loss': float(losses['value'].detach().item()),
            'l2': float(losses['l2'].detach().item()),
            'entropy': float(losses['entropy'].detach().item()),
        }
        if 'delta_aux' in losses:
            breakdown['delta_aux'] = float(losses['delta_aux'].detach().item())

        return LossResult(loss=losses['total'], breakdown=breakdown)
