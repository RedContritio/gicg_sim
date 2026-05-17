"""BC training loss + match-rate metrics.

Helper module for ``bc.train`` (private — module prefix ``_`` marks internal).
"""

from __future__ import annotations

import torch

from training.core.network import ActorCritic
from training.core.structural import compute_structural_obspos, compute_structural_values


def forward_batch(net: ActorCritic, batch: dict, device):
    """Run ActorCritic forward (mirrors agent.forward_batch but standalone
    for BC — no AZAgent wrapper needed). Returns (logits, value)."""

    def _t(key, dtype):
        return torch.as_tensor(batch[key], dtype=dtype, device=device)

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
    recent_damage = _t('recent_damage', torch.float32)
    prepare_skill = _t('prepare_skill', torch.float32)
    modifier_log = _t('modifier_log', torch.float32)

    hook_emb = net.hook_encoder(hook_types, hook_values, hook_mask)
    structural_obspos = compute_structural_obspos(counter_sids, active_slot_mask)
    structural_values = compute_structural_values(counter_values, structural_obspos)

    out = net(
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
        recent_damage,
        prepare_skill,
        modifier_log,
    )
    # Generic ActorCritic returns dict; BC consumes (logits, value) for
    # masked CE + optional value MSE (BC4.1 + BC4.2 ckpt warm-start compat).
    return out['policy'], out['value']


def soft_target_ce_loss(logits: torch.Tensor, tied_mask: torch.Tensor, legal_mask: torch.Tensor) -> torch.Tensor:
    """Soft-target CE: target = uniform over tied_mask, mask logits by
    legal_mask. Matches PPO s016d soft-target loss."""
    neg_inf = torch.finfo(logits.dtype).min
    masked_logits = torch.where(legal_mask, logits, torch.full_like(logits, neg_inf))
    log_probs = torch.log_softmax(masked_logits, dim=-1)
    n_tied = tied_mask.sum(dim=-1).clamp(min=1).float()
    target_dist = tied_mask.float() / n_tied.unsqueeze(-1)
    loss = -(target_dist * log_probs).sum(dim=-1).mean()
    return loss


def hard_match_rate(logits: torch.Tensor, chosen: torch.Tensor, legal_mask: torch.Tensor) -> float:
    """argmax over legal_mask matches teacher's chosen action."""
    neg_inf = torch.finfo(logits.dtype).min
    masked = torch.where(legal_mask, logits, torch.full_like(logits, neg_inf))
    pred = masked.argmax(dim=-1)
    return float((pred == chosen).float().mean().item())


def soft_match_rate(logits: torch.Tensor, tied_mask: torch.Tensor, legal_mask: torch.Tensor) -> float:
    """argmax falls within teacher's tied-best set."""
    neg_inf = torch.finfo(logits.dtype).min
    masked = torch.where(legal_mask, logits, torch.full_like(logits, neg_inf))
    pred = masked.argmax(dim=-1)
    pred_in_tied = tied_mask.gather(1, pred.unsqueeze(-1)).squeeze(-1)
    return float(pred_in_tied.float().mean().item())
