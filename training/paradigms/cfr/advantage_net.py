"""AdvantageNet + regret_to_policy.

AdvantageNet is used only inside the CFR training loop (never shipped
in a ckpt). Output is the per-action regret vector.
"""

from __future__ import annotations

from training.core.artifact_io import load_checkpoint, save_checkpoint

import torch
import torch.nn as nn

from training.paradigms.cfr.strategy_net import CFRNetConfig, _CFRTrunk, _pointer_net_logits


class AdvantageNet(nn.Module):
    """Regret network, used only inside the CFR training loop."""

    KIND = 'cfr_advantage'

    def __init__(self, cfg: CFRNetConfig):
        super().__init__()
        self.cfg = cfg
        self.trunk = _CFRTrunk(cfg)

    def forward(
        self,
        counter_values,
        counter_sids,
        active_slot_mask,
        hook_emb_cached,
        hook_mask,
        card_buckets,
        enemy_sizes,
        meta,
        action_refs,
        action_payments,
        structural_values,
        char_skill_refs,
        definition_links,
        buffs=None,
    ):
        """Returns (B, max_actions) regret scores. No nonlinearity."""
        out = self.trunk.encode(
            counter_values,
            counter_sids,
            active_slot_mask,
            hook_emb_cached,
            hook_mask,
            card_buckets,
            enemy_sizes,
            meta,
            action_refs,
            action_payments,
            structural_values,
            char_skill_refs,
            definition_links,
            buffs=buffs,
        )
        return _pointer_net_logits(out)

    def save(self, path: str) -> None:
        """Optional debug snapshot (not part of inference deliverable)."""
        save_checkpoint(
            {
                'cfg': vars(self.cfg),
                'net': self.state_dict(),
                'kind': self.KIND,
            },
            path,
        )

    def load(self, path: str, map_location: str = 'cpu') -> None:
        blob = load_checkpoint(path, weights_only=True, map_location=map_location)
        if not isinstance(blob, dict) or 'net' not in blob:
            raise RuntimeError(f"AdvantageNet.load: {path} missing 'net'")
        if blob.get('kind') not in (self.KIND, None):
            raise RuntimeError(f'AdvantageNet.load: ckpt kind={blob.get("kind")!r} != expected {self.KIND!r}')
        self.load_state_dict(blob['net'])


def regret_to_policy(
    regret: torch.Tensor,
    legal_mask: torch.Tensor,
) -> torch.Tensor:
    """Regret-matching: policy ∝ relu(regret) over legal actions."""
    if not torch.all(torch.isfinite(regret)):
        raise ValueError('regret_to_policy: input regret contains NaN or Inf')
    pos = torch.clamp(regret, min=0.0) * legal_mask.float()
    total = pos.sum(dim=-1, keepdim=True)
    uniform = legal_mask.float()
    uniform = uniform / uniform.sum(dim=-1, keepdim=True).clamp(min=1.0)
    has_positive = total > 0.0
    normalized = pos / total.clamp(min=1e-12)
    return torch.where(has_positive, normalized, uniform)
