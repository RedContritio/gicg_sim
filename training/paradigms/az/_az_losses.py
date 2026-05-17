"""AZ loss computation — policy + value + optional L2 + optional entropy
regularization. Keep this module import-light; only torch + typing."""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


def az_losses(
    logits: torch.Tensor,
    value: torch.Tensor,
    legal_mask: torch.Tensor,
    pi_target: torch.Tensor,
    z_target: torch.Tensor,
    model: Optional[nn.Module] = None,
    l2_coef: float = 0.0,
    entropy_coef: float = 0.0,
) -> dict:
    """AlphaZero-style losses.

    Args:
        logits:     (B, max_actions) raw logits from ActorCritic.forward
        value:      (B,) tanh-bounded value head output
        legal_mask: (B, max_actions) bool — True on legal slots
        pi_target:  (B, max_actions) float — MCTS visit distribution,
                    **exactly zero on illegal slots**, sums to 1 over
                    legal. The contract is checked explicitly below:
                    any non-zero mass on illegal slots raises
                    ValueError so caller bugs surface here instead of
                    being absorbed into the loss.
        z_target:   (B,) float in {-1, 0, 1} from the acting player's
                    perspective (engine winner mapped through
                    gicg_env.env._terminal_z and flipped for P1)
        model:      nn.Module whose params contribute to the L2 term.
                    Required iff l2_coef > 0.
        l2_coef:    scalar multiplier on sum(w**2). Set to 0 to disable
                    (e.g. when using AdamW weight_decay instead).

    Returns:
        dict with 4 scalar tensors: ``total``, ``value``, ``policy``,
        ``l2``. The caller does ``total.backward()``.
    """
    # --- Contract check: pi_target must be exactly 0 on illegal slots.
    # If a caller constructs pi_target via visits/sum(visits) this is
    # naturally true (illegal slots get 0 visits). Any non-zero mass
    # here is a caller bug — raise immediately rather than bury it in
    # the loss.
    if ((pi_target != 0) & ~legal_mask).any().item():
        raise ValueError(
            'az_losses: pi_target has non-zero mass on illegal slots '
            '(pi_target is a distribution over legal actions; illegal '
            'positions must hold exactly 0)'
        )

    # --- Policy loss: masked log_softmax.
    masked_logits = logits.masked_fill(~legal_mask, float('-inf'))
    log_probs = F.log_softmax(masked_logits, dim=-1)
    log_probs = log_probs.masked_fill(~legal_mask, 0.0)
    policy_loss = -(pi_target * log_probs).sum(dim=-1).mean()

    value_loss = F.mse_loss(value, z_target)

    l2 = torch.zeros((), device=logits.device, dtype=logits.dtype)
    if l2_coef > 0.0:
        if model is None:
            raise ValueError('az_losses: l2_coef > 0 requires model= argument')
        for name, p in model.named_parameters():
            if not p.requires_grad:
                continue
            if p.dim() < 2:
                continue  # biases, LayerNorm weights/biases
            l2 = l2 + (p * p).sum()
        l2 = l2 * l2_coef

    entropy = torch.zeros((), device=logits.device, dtype=logits.dtype)
    if entropy_coef > 0.0:
        probs = torch.softmax(masked_logits, dim=-1)
        entropy = -(probs * log_probs).sum(dim=-1).mean()

    total = value_loss + policy_loss + l2 - entropy_coef * entropy
    return {
        'total': total,
        'value': value_loss,
        'policy': policy_loss,
        'l2': l2,
        'entropy': entropy,
    }
