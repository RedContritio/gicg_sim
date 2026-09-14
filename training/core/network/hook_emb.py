"""Hook embedding cache and character-skill gather helpers.

The cached hook embeddings feed the cross-attention block;
``char_skill_pool`` gathers
hook_emb at char-skill ref positions (P0+P1 skill identification).

The helpers are shared by AZ, DMC, and PPO."""

from __future__ import annotations

import torch
import torch.nn as nn

from training.core.obs_constants import OBS_MAX_CHARS


class CharSkillPooler(nn.Module):
    """Pool hook_emb at char_skill_refs positions. Ref ≥ 0 means valid
    skill slot; -1 means unbound — masked out before mean."""

    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.d_model = d_model

    def forward(self, hook_emb: torch.Tensor, char_skill_refs: torch.Tensor) -> torch.Tensor:
        B = hook_emb.shape[0]
        n_hooks_cached = hook_emb.shape[1]
        skill_refs_flat = char_skill_refs.reshape(B, -1)
        skill_ref_valid = skill_refs_flat >= 0
        skill_ref_idx = skill_refs_flat.clamp(min=0, max=max(n_hooks_cached - 1, 0))
        gathered = torch.gather(
            hook_emb,
            dim=1,
            index=skill_ref_idx.unsqueeze(-1).expand(-1, -1, self.d_model),
        )
        gathered = gathered * skill_ref_valid.unsqueeze(-1).float()
        denom = skill_ref_valid.sum(dim=1, keepdim=True).clamp(min=1).float()
        return gathered.sum(dim=1) / denom


class CharSlotEmbedder(nn.Module):
    """Per-char slot embedding lookup (used for SWITCH action emb)."""

    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.emb = nn.Embedding(OBS_MAX_CHARS, d_model)
        self.d_model = d_model

    def forward(self, char_idx: torch.Tensor) -> torch.Tensor:
        safe = char_idx.clamp(min=0, max=OBS_MAX_CHARS - 1).long()
        return self.emb(safe)
