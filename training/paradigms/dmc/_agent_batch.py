"""DMC batched tensor preparation and Q-network forward pass."""

from __future__ import annotations

import torch

from training.core.structural import compute_structural_obspos, compute_structural_values


class _DmcBatchMixin:
    def forward_batch(self, batch: dict):
        """Batched forward (same as AZ for now). Returns (logits, value, delta_pred)."""

        def _t(key, dtype):
            x = batch[key]
            if isinstance(x, torch.Tensor):
                return x.to(self.device).to(dtype)
            return torch.as_tensor(x, dtype=dtype, device=self.device)

        counter_values = _t('counter_values', torch.float32)
        counter_sids = _t('counter_sids', torch.long)
        active_slot_mask = _t('active_slot_mask', torch.bool)
        hook_ir = _t('hook_ir', torch.long)
        hook_mask = _t('hook_mask', torch.bool)
        definition_links = _t('definition_links', torch.long)
        card_buckets = _t('card_buckets', torch.float32)
        enemy_sizes = _t('enemy_sizes', torch.float32)
        meta = _t('meta', torch.float32)
        action_refs = _t('action_refs', torch.long)
        action_payments = _t('action_payments', torch.float32)
        char_skill_refs = _t('char_skill_refs', torch.long)
        recent_damage = _t('recent_damage', torch.float32)
        prepare_skill = _t('prepare_skill', torch.float32)
        modifier_log = _t('modifier_log', torch.float32)

        hook_emb = self.net.hook_encoder(hook_ir, hook_mask)
        structural_obspos = compute_structural_obspos(counter_sids, active_slot_mask)
        structural_values = compute_structural_values(counter_values, structural_obspos)

        out = self.net(
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
            buffs=_t('buffs', torch.float32) if 'buffs' in batch else None,
            definition_links=definition_links,
        )
        # DMC uses single Q head; loss expects (logits, value, delta) 3-tuple
        # (DMCLogitAsQLoss only reads logits, the latter two are unused
        # placeholders for AZ-style protocol compatibility).
        return out['q'], None, None
