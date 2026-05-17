"""BCLoss — CE (hard target) / KL (soft teacher target) — implements
LossComputer protocol.

Spec ref: paradigm-bc/spec.md BC2:
 - BC2.1 loss_kind = "ce" (cross-entropy on hard expert action)
   或 "kl" (KL on teacher soft distribution)
 - BC2.2 hard target = ``chosen_action``;soft target = uniform over
   ``tied_mask``(matches bc/legacy/bc_loss.soft_target_ce_loss + ppo s016d)
 - BC2.3 No value loss when ``value_coef = 0.0``;no entropy bonus

Reads ``batch.data['fields']`` (BCDataset.build_batch output dict) so the
driver path is uniform with other paradigms (``batch.data`` 是 dict).
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from training.core.protocols import Batch, LossResult


def _soft_target_ce(logits: torch.Tensor, tied_mask: torch.Tensor, legal_mask: torch.Tensor) -> torch.Tensor:
    """Soft-target CE: target = uniform over ``tied_mask``, mask logits
    by ``legal_mask``. Matches bc/legacy/bc_loss.soft_target_ce_loss verbatim
    so r009 reproduction is bit-identical."""
    neg_inf = torch.finfo(logits.dtype).min
    masked_logits = torch.where(legal_mask, logits, torch.full_like(logits, neg_inf))
    log_probs = torch.log_softmax(masked_logits, dim=-1)
    n_tied = tied_mask.sum(dim=-1).clamp(min=1).float()
    target_dist = tied_mask.float() / n_tied.unsqueeze(-1)
    return -(target_dist * log_probs).sum(dim=-1).mean()


def _hard_target_ce(logits: torch.Tensor, chosen: torch.Tensor, legal_mask: torch.Tensor) -> torch.Tensor:
    """Hard CE on chosen action with legal_mask -inf padding."""
    neg_inf = torch.finfo(logits.dtype).min
    masked_logits = torch.where(legal_mask, logits, torch.full_like(logits, neg_inf))
    log_probs = torch.log_softmax(masked_logits, dim=-1)
    return -log_probs.gather(1, chosen.unsqueeze(-1)).squeeze(-1).mean()


class BCLoss:
    """LossComputer for BC. Reads ``batch.data['fields']`` dict that
    BCDataset.build_batch produced (chosen_action / tied_mask /
    legal_mask / terminal_z + obs fields)."""

    def __init__(self, paradigm_cfg: Any) -> None:
        self.cfg = paradigm_cfg

    def compute(self, network: Any, batch: Batch) -> LossResult:
        if 'fields' not in batch.data:
            raise ValueError(f"BCLoss.compute: batch.data missing 'fields' key (got {sorted(batch.data.keys())})")
        fields = batch.data['fields']

        if not hasattr(network, 'forward_batch'):
            raise TypeError(f'BCLoss.compute: network must expose forward_batch(dict); got {type(network).__name__}')
        logits, value = network.forward_batch(fields)
        device = logits.device

        legal_t = torch.as_tensor(fields['legal_mask'], dtype=torch.bool, device=device)

        loss_kind = getattr(self.cfg, 'loss_kind', 'ce') if self.cfg is not None else 'ce'
        if loss_kind == 'kl':
            tied_t = torch.as_tensor(fields['tied_mask'], dtype=torch.bool, device=device)
            pol_loss = _soft_target_ce(logits, tied_t, legal_t)
        else:
            chosen_t = torch.as_tensor(fields['chosen_action'], dtype=torch.long, device=device)
            pol_loss = _hard_target_ce(logits, chosen_t, legal_t)

        value_coef = float(getattr(self.cfg, 'value_coef', 0.0) if self.cfg is not None else 0.0)
        if value_coef > 0.0:
            z_t = torch.as_tensor(fields['terminal_z'], dtype=torch.float32, device=device)
            val_loss = nn.functional.mse_loss(value, z_t)
            loss = pol_loss + value_coef * val_loss
            val_item = float(val_loss.detach().item())
        else:
            loss = pol_loss
            val_item = 0.0

        breakdown = {
            'loss': float(loss.detach().item()),
            'policy_loss': float(pol_loss.detach().item()),
            'value_loss': val_item,
            'loss_kind': 1.0 if loss_kind == 'kl' else 0.0,
        }
        return LossResult(loss=loss, breakdown=breakdown)
