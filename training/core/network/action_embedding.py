"""Encode rule, switch, target, tune, reroll, and payment action features."""

import torch

from training.core.obs_constants import ACTION_CARD, ACTION_SWITCH, ACTION_END_TURN, ACTION_TUNE, ACTION_REROLL
from training.core.network.action_buff_embedding import selected_buff_embeddings


def encode_actions(net, hook_emb, action_refs, action_payments, buff_rows=None, buff_tokens=None):
    B, n_act, _ = action_refs.shape
    kinds = action_refs[..., 0]
    hook_idx = action_refs[..., 1]
    char_idx = action_refs[..., 2]
    n_hooks_cached = hook_emb.shape[1]
    hook_valid_idx = hook_idx.clamp(min=0).long().clamp(max=max(n_hooks_cached - 1, 0))
    reroll = kinds == ACTION_REROLL
    mask_hook = (hook_idx >= 0) & ~reroll
    gathered = torch.gather(
        hook_emb,
        dim=1,
        index=hook_valid_idx.unsqueeze(-1).expand(-1, -1, net.d_model),
    )
    char_embs = net.char_slot_emb(torch.where(reroll, -1, char_idx).clamp_min(-1))
    end_emb = net.end_turn_emb.view(1, 1, -1).expand(B, n_act, -1)

    action_emb = torch.zeros_like(gathered)
    action_emb = torch.where(mask_hook.unsqueeze(-1), gathered, action_emb)
    action_emb = torch.where((kinds == ACTION_SWITCH).unsqueeze(-1), char_embs, action_emb)
    action_emb = torch.where((kinds == ACTION_END_TURN).unsqueeze(-1), end_emb, action_emb)

    targeted = (kinds == ACTION_CARD) & (char_idx >= 0)
    target_emb = net.card_target_emb(char_idx.clamp(0, net.card_target_emb.num_embeddings - 1).long())
    action_emb = action_emb + target_emb * targeted.unsqueeze(-1)
    buff_refs = torch.where(kinds == ACTION_CARD, char_idx, -1)
    buff_targets = selected_buff_embeddings(buff_refs, buff_rows, buff_tokens)
    if buff_targets is not None:
        action_emb = action_emb + buff_targets

    tune_emb = net.tune_source_emb(char_idx.clamp(0, 7).long()) + net.tune_action_emb
    action_emb = action_emb + tune_emb * (kinds == ACTION_TUNE).unsqueeze(-1)

    if reroll.any():
        invalid = (hook_idx < 0) | (char_idx < 0) | (char_idx > 8) | ((char_idx == 8) & (hook_idx != 0))
        if (invalid & reroll).any():
            raise ValueError('invalid reroll action quantity/color')
        count = hook_idx.clamp_min(0).float()
        numeric = torch.stack((count, count.log1p()), dim=-1)
        reroll_emb = net.reroll_color_emb(char_idx.clamp(0, 8).long()) + net.reroll_count_proj(numeric)
        action_emb = action_emb + reroll_emb * reroll.unsqueeze(-1)

    pay_emb = net.dice_combo_proj(action_payments.float())
    action_emb = action_emb + pay_emb
    action_emb = net.action_emb_norm(action_emb)

    return action_emb
