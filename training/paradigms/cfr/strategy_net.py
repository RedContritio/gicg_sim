"""CFRStrategyNet + shared trunk.

``_CFRTrunk`` mirrors the encoder portion of ActorCritic but is its own
module — CFR and AZ train independent weights so the sharing is of
architecture code, not of weights.

``CFRStrategyNet`` is the inference-time deliverable. Output interface
matches ActorCritic's primary outputs (``(logits, value)``) so MCTS
wrapping works unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn

from training.core.network.encoder import (
    CardEncoder,
    CounterEncoder,
    CrossAttentionBlock,
    HookEncoder,
)
from training.core.obs_constants import (
    ACTION_END_TURN,
    ACTION_SWITCH,
    DICE_COLOR_COUNT,
    N_STRUCTURAL,
    OBS_MAX_CHARS,
    OBS_META_SIZE,
)


@dataclass
class CFRNetConfig:
    """Shape parameters for CFR networks."""

    n_counter_slots: int
    n_hooks: int
    max_ops_per_hook: int
    max_actions: int
    fields_per_op: int = 5
    d_model: int = 64
    dropout: float = 0.0
    n_cross_layers: int = 2


class _CFRTrunk(nn.Module):
    """Encoder trunk shared across CFRStrategyNet and AdvantageNet."""

    def __init__(self, cfg: CFRNetConfig):
        super().__init__()
        self.cfg = cfg
        d = cfg.d_model

        self.hook_encoder = HookEncoder(
            opcode_vocab=16,
            operand_vocab=2048,
            token_dim=d,
            n_heads=4,
            n_layers=2,
            max_ops=cfg.max_ops_per_hook,
            dropout=cfg.dropout,
        )
        self.counter_encoder = CounterEncoder(max_slots=2000, embed_dim=d)
        self.card_encoder = CardEncoder(d_model=d)

        self.cross_layers = nn.ModuleList(
            [CrossAttentionBlock(d, n_heads=4, dropout=cfg.dropout) for _ in range(cfg.n_cross_layers)]
        )

        self.meta_proj = nn.Linear(OBS_META_SIZE, d)
        self.struct_head = nn.Linear(N_STRUCTURAL, d)

        self.char_slot_emb = nn.Embedding(OBS_MAX_CHARS, d)
        self.end_turn_emb = nn.Parameter(torch.zeros(d))
        nn.init.normal_(self.end_turn_emb, std=0.02)
        self.action_emb_norm = nn.LayerNorm(d)
        self.dice_combo_proj = nn.Sequential(
            nn.Linear(DICE_COLOR_COUNT, d),
            nn.ReLU(),
            nn.Linear(d, d),
        )

        self._state_input_dim = 6 * d
        self.state_proj = nn.Sequential(
            nn.Linear(self._state_input_dim, 2 * d),
            nn.ReLU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(2 * d, d),
        )

    def encode(
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
    ):
        """Run the encoder. Returns a dict of intermediate tensors."""
        d = self.cfg.d_model

        counter_emb, counter_mask = self.counter_encoder(
            counter_values,
            counter_sids,
            active_slot_mask,
        )
        hook_emb = hook_emb_cached
        for layer in self.cross_layers:
            counter_emb, hook_emb = layer(
                counter_emb,
                hook_emb,
                counter_mask,
                hook_mask,
            )

        counter_valid = counter_mask.unsqueeze(-1).float()
        counter_pool = (counter_emb * counter_valid).sum(dim=1) / counter_valid.sum(dim=1).clamp(min=1)
        hook_valid = hook_mask.unsqueeze(-1).float()
        hook_pool = (hook_emb * hook_valid).sum(dim=1) / hook_valid.sum(dim=1).clamp(min=1)

        B = hook_emb.shape[0]
        n_hooks_cached = hook_emb.shape[1]
        skill_refs_flat = char_skill_refs.reshape(B, -1)
        skill_ref_valid = skill_refs_flat >= 0
        skill_ref_idx = skill_refs_flat.clamp(
            min=0,
            max=max(n_hooks_cached - 1, 0),
        )
        skill_gathered = torch.gather(
            hook_emb,
            dim=1,
            index=skill_ref_idx.unsqueeze(-1).expand(-1, -1, d),
        )
        skill_gathered = skill_gathered * skill_ref_valid.unsqueeze(-1).float()
        denom = skill_ref_valid.sum(dim=1, keepdim=True).clamp(min=1).float()
        char_skill_pool = skill_gathered.sum(dim=1) / denom

        meta_emb = self.meta_proj(meta)
        card_emb = self.card_encoder(card_buckets, enemy_sizes)
        struct_feat = self.struct_head(structural_values)

        combined = torch.cat(
            [counter_pool, hook_pool, char_skill_pool, card_emb, meta_emb, struct_feat],
            dim=-1,
        )
        state_vec = self.state_proj(combined)

        N_act = action_refs.shape[1]
        kinds = action_refs[..., 0]
        hook_idx = action_refs[..., 1]
        char_idx = action_refs[..., 2]

        hook_valid_idx = (
            hook_idx.clamp(min=0)
            .long()
            .clamp(
                max=max(n_hooks_cached - 1, 0),
            )
        )
        mask_hook = hook_idx >= 0
        gathered = torch.gather(
            hook_emb,
            dim=1,
            index=hook_valid_idx.unsqueeze(-1).expand(-1, -1, d),
        )
        safe_char_idx = char_idx.clamp(
            min=0,
            max=OBS_MAX_CHARS - 1,
        ).long()
        char_embs = self.char_slot_emb(safe_char_idx)
        end_emb = self.end_turn_emb.view(1, 1, -1).expand(B, N_act, -1)

        action_emb = torch.zeros_like(gathered)
        action_emb = torch.where(mask_hook.unsqueeze(-1), gathered, action_emb)
        action_emb = torch.where(
            (kinds == ACTION_SWITCH).unsqueeze(-1),
            char_embs,
            action_emb,
        )
        action_emb = torch.where(
            (kinds == ACTION_END_TURN).unsqueeze(-1),
            end_emb,
            action_emb,
        )

        pay_emb = self.dice_combo_proj(action_payments.float())
        action_emb = action_emb + pay_emb
        action_emb = self.action_emb_norm(action_emb)

        return {
            'state_vec': state_vec,
            'action_emb': action_emb,
            'combined': combined,
            'hook_emb': hook_emb,
        }


def _pointer_net_logits(encoder_out: dict) -> torch.Tensor:
    """Pointer-net per-action score: dot(state_vec, action_emb)."""
    state_vec = encoder_out['state_vec']
    action_emb = encoder_out['action_emb']
    return (state_vec.unsqueeze(1) * action_emb).sum(-1)


class CFRStrategyNet(nn.Module):
    """Strategy (policy) + value network, the deliverable CFR ckpt."""

    KIND = 'cfr_strategy'

    def __init__(self, cfg: CFRNetConfig):
        super().__init__()
        self.cfg = cfg
        d = cfg.d_model
        self.trunk = _CFRTrunk(cfg)
        self.value_head = nn.Sequential(
            nn.Linear(self.trunk._state_input_dim, 2 * d),
            nn.ReLU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(2 * d, 1),
        )

    @property
    def hook_encoder(self):
        return self.trunk.hook_encoder

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
    ):
        """Returns (logits, value)."""
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
        )
        logits = _pointer_net_logits(out)
        value = torch.tanh(self.value_head(out['combined']).squeeze(-1))
        return logits, value

    def save(self, path: str) -> None:
        torch.save(
            {
                'cfg': vars(self.cfg),
                'net': self.state_dict(),
                'kind': self.KIND,
            },
            path,
        )

    def load(self, path: str, map_location: str = 'cpu') -> None:
        blob = torch.load(path, weights_only=True, map_location=map_location)
        if not isinstance(blob, dict) or 'net' not in blob:
            raise RuntimeError(f"CFRStrategyNet.load: {path} missing 'net'")
        if blob.get('kind') not in (self.KIND, None):
            raise RuntimeError(f'CFRStrategyNet.load: ckpt kind={blob.get("kind")!r} != expected {self.KIND!r}')
        self.load_state_dict(blob['net'])
