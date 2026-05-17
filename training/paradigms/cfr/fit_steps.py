"""Per-iteration fit steps for CFRTrainer — advantage regret fit +
joint policy/value fit. Factored out so ``train.py`` stays below the
line-limit."""

from __future__ import annotations

from typing import Optional

import numpy as np
import torch

from training.paradigms.cfr.advantage_net import AdvantageNet
from training.core.structural import (
    compute_structural_obspos,
    compute_structural_values,
)


def forward_cfr_batch(
    trainer,
    net,
    batch: dict,
    returns_value: bool = False,
):
    """Forward a reservoir batch through the network. Re-encodes hooks
    from raw tokens so hook_encoder trains with gradients. Returns
    regret (AdvantageNet) or (logits, value) (StrategyNet)."""

    def _t(key, dtype):
        x = batch[key]
        if isinstance(x, torch.Tensor):
            return x.to(trainer.device).to(dtype)
        return torch.as_tensor(x, dtype=dtype, device=trainer.device)

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

    hook_emb = net.trunk.hook_encoder(
        hook_types,
        hook_values,
        hook_mask,
    )
    structural_obspos = compute_structural_obspos(
        counter_sids,
        active_slot_mask,
    )
    structural_values = compute_structural_values(counter_values, structural_obspos)

    result = net(
        counter_values=counter_values,
        counter_sids=counter_sids,
        active_slot_mask=active_slot_mask,
        hook_emb_cached=hook_emb,
        hook_mask=hook_mask,
        card_buckets=card_buckets,
        enemy_sizes=enemy_sizes,
        meta=meta,
        action_refs=action_refs,
        action_payments=action_payments,
        structural_values=structural_values,
        char_skill_refs=char_skill_refs,
    )
    if returns_value:
        logits, value = result
        return logits, value
    return result


def clip_grads(trainer, net: torch.nn.Module) -> None:
    m = trainer.train_cfg.grad_clip_max_norm
    if m and m > 0:
        torch.nn.utils.clip_grad_norm_(net.parameters(), max_norm=m)


def fit_advantage(trainer, iteration: int) -> float:
    """Fit each per-player AdvantageNet on its own buffer."""
    all_losses: list[float] = []
    for p in range(2):
        buf = trainer.advantage_buffers[p]
        if len(buf) == 0:
            continue

        if trainer.train_cfg.advantage_reset_each_iter and iteration > 0:
            torch.manual_seed(
                trainer.train_cfg.seed + iteration * 7919 + p,
            )
            trainer.advantage_nets[p] = AdvantageNet(trainer.net_cfg).to(trainer.device)
            trainer.traverser.advantage_nets[p] = trainer.advantage_nets[p]
            trainer.adv_optimizers[p] = torch.optim.Adam(
                trainer.advantage_nets[p].parameters(),
                lr=trainer.train_cfg.advantage_lr,
            )

        net = trainer.advantage_nets[p]
        opt = trainer.adv_optimizers[p]
        net.train()
        for _ in range(trainer.train_cfg.advantage_fit_steps_per_iter):
            batch = buf.sample(trainer.train_cfg.fit_batch_size, trainer.rng)
            pred = forward_cfr_batch(trainer, net, batch)
            target = torch.as_tensor(
                batch['regret'],
                dtype=torch.float32,
                device=trainer.device,
            )
            legal_mask = torch.as_tensor(
                batch['legal_mask'],
                dtype=torch.bool,
                device=trainer.device,
            )
            legal_f = legal_mask.float()
            sq = (pred - target).pow(2) * legal_f
            per_sample_n = legal_f.sum(dim=-1).clamp(min=1.0)
            per_sample_loss = sq.sum(dim=-1) / per_sample_n
            loss = per_sample_loss.mean()
            opt.zero_grad()
            loss.backward()
            clip_grads(trainer, net)
            opt.step()
            all_losses.append(float(loss.item()))
    return float(np.mean(all_losses)) if all_losses else float('nan')


def fit_strategy_joint(trainer) -> tuple[Optional[float], Optional[float]]:
    """Joint policy + value fit."""
    has_pol = len(trainer.strategy_buffer) > 0
    has_val = len(trainer.value_buffer) > 0
    if not (has_pol or has_val):
        return None, None

    trainer.strategy_net.train()
    pol_losses: list[float] = []
    val_losses: list[float] = []
    alpha = trainer.train_cfg.value_loss_alpha

    for _ in range(trainer.train_cfg.strategy_fit_steps):
        trainer.strat_optimizer.zero_grad()
        total = torch.zeros((), device=trainer.device)

        if has_pol:
            p_batch = trainer.strategy_buffer.sample(
                trainer.train_cfg.fit_batch_size,
                trainer.rng,
            )
            logits, _ = forward_cfr_batch(
                trainer,
                trainer.strategy_net,
                p_batch,
                returns_value=True,
            )
            target_p = torch.as_tensor(
                p_batch['policy'],
                dtype=torch.float32,
                device=trainer.device,
            )
            legal_mask = torch.as_tensor(
                p_batch['legal_mask'],
                dtype=torch.bool,
                device=trainer.device,
            )
            masked_logits = logits.masked_fill(~legal_mask, -1e9)
            log_probs = torch.log_softmax(masked_logits, dim=-1)
            ce_per_row = -(target_p * log_probs).sum(dim=-1)
            iter_batch = torch.as_tensor(
                p_batch['iteration'],
                dtype=torch.float32,
                device=trainer.device,
            )
            weights = iter_batch / iter_batch.max().clamp(min=1.0)
            policy_loss = (ce_per_row * weights).mean()
            total = total + policy_loss
            pol_losses.append(float(policy_loss.item()))

        if has_val:
            v_batch = trainer.value_buffer.sample(
                trainer.train_cfg.fit_batch_size,
                trainer.rng,
            )
            _, value = forward_cfr_batch(
                trainer,
                trainer.strategy_net,
                v_batch,
                returns_value=True,
            )
            target_v = torch.as_tensor(
                v_batch['outcome'],
                dtype=torch.float32,
                device=trainer.device,
            )
            value_loss = (value - target_v).pow(2).mean()
            total = total + alpha * value_loss
            val_losses.append(float(value_loss.item()))

        total.backward()
        clip_grads(trainer, trainer.strategy_net)
        trainer.strat_optimizer.step()

    return (
        float(np.mean(pol_losses)) if pol_losses else None,
        float(np.mean(val_losses)) if val_losses else None,
    )
