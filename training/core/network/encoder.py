"""Paradigm-agnostic trunk encoders.

Adapted from training/framework/network/trunk.py — exact algorithmic
behavior preserved (HookEncoder Transformer pooling / CounterEncoder
SID embedding + active mask gather / CardEncoder bucket × slot decomp
with single count_proj per E2 fix / CrossAttention bidirectional with
NaN-guard).

Imports core/obs_constants (paradigm-agnostic) instead of framework.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from training.core.obs_constants import (
    OBS_ENEMY_SIZES,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
)


class HookEncoder(nn.Module):
    """IR-4 per-hook Transformer encoder (replaces the IR-1.6 legacy
    token-pair encoder). Consumes the IR obs format:

      hook_ir: (B, N, max_ops, fields_per_op=5) int — opcode/dst/op1/op2/op3
      hook_mask: (B, N) bool — which hook slots are active

    Returns (B, N, token_dim) — one embedding per hook. Inside a hook,
    each op is embedded as (opcode_embed + sum-of-operand_embed + pos_embed);
    Transformer attends across ops; mean-pooled over non-NOP ops.

    The vocab for operand_embed is sized to cover the union of all
    operand semantic spaces (reg indices 0..MaxRegs, ctx-field/enum/
    method/builtin/kwarg/bridge token IDs in range 0..~512 per
    tokenizer_tokens.go). Negative operand values (NullReg=-1) are
    clamped to 0 — the encoder masks unused operand slots via opcode.
    """

    def __init__(
        self,
        opcode_vocab: int = 16,
        operand_vocab: int = 2048,
        token_dim: int = 64,
        n_heads: int = 4,
        n_layers: int = 2,
        max_ops: int = 64,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.opcode_embed = nn.Embedding(opcode_vocab, token_dim)
        # Single shared embedding table for all 4 operand slots (dst+op1+op2+op3).
        # Operand semantics depend on opcode; the encoder learns to dispatch
        # implicitly via the opcode_embed signal.
        self.operand_embed = nn.Embedding(operand_vocab, token_dim)
        self.pos_embed = nn.Embedding(max_ops, token_dim)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=token_dim,
            nhead=n_heads,
            dim_feedforward=token_dim * 4,
            batch_first=True,
            dropout=dropout,
        )
        self.transformer = nn.TransformerEncoder(
            encoder_layer,
            num_layers=n_layers,
            enable_nested_tensor=False,
        )
        self.token_dim = token_dim
        self.max_ops = max_ops
        self.opcode_vocab = opcode_vocab
        self.operand_vocab = operand_vocab

    def forward(self, hook_ir, hook_mask):
        """hook_ir: (B, N, max_ops, 5) int long; hook_mask: (B, N) bool (unused
        — per-op padding handled internally by opcode==0 mask)."""
        B, N, T, F = hook_ir.shape  # F=5
        flat = hook_ir.reshape(B * N, T, F).long()
        opcode = flat[..., 0].clamp(min=0, max=self.opcode_vocab - 1)
        operands = flat[..., 1:5].clamp(min=0, max=self.operand_vocab - 1)
        pos = torch.arange(T, device=flat.device).unsqueeze(0).expand(B * N, -1)
        # Per-op embedding = opcode + sum(4 operands) + pos.
        op_emb = self.opcode_embed(opcode)
        operand_emb = self.operand_embed(operands).sum(dim=-2)
        tok = op_emb + operand_emb + self.pos_embed(pos)
        pad_mask = flat[..., 0] == 0  # OpNop padding
        out = self.transformer(tok, src_key_padding_mask=pad_mask)
        valid = (~pad_mask).unsqueeze(-1).float()
        pooled = (out * valid).sum(dim=1) / valid.sum(dim=1).clamp(min=1)
        pooled = torch.nan_to_num(pooled, 0.0)
        return pooled.reshape(B, N, self.token_dim)


class CounterEncoder(nn.Module):
    """SID-aware counter encoder. ``active_slot_mask`` (from static
    min/max metadata) selects real counters — value-based filtering is
    incorrect because 0 is meaningful for many counters."""

    def __init__(self, max_slots: int = 2000, embed_dim: int = 64) -> None:
        super().__init__()
        self.value_proj = nn.Linear(1, embed_dim)
        self.sid_embed = nn.Embedding(max_slots, embed_dim)
        self.embed_dim = embed_dim

    def forward(self, counter_values, counter_sids, active_slot_mask):
        val_emb = self.value_proj(counter_values.unsqueeze(-1))
        sid_emb = self.sid_embed(counter_sids.clamp(0, 1999))
        all_emb = val_emb + sid_emb

        # Use amax to stay on-device; only one host sync per forward.
        max_active_t = active_slot_mask.sum(dim=1).amax().clamp_min(1)
        max_active = int(max_active_t)
        _, indices = active_slot_mask.float().sort(dim=1, descending=True, stable=True)
        idx_trunc = indices[:, :max_active]
        emb_out = all_emb.gather(1, idx_trunc.unsqueeze(-1).expand(-1, -1, self.embed_dim))
        mask_out = active_slot_mask.gather(1, idx_trunc)
        return emb_out, mask_out


class CardEncoder(nn.Module):
    """Bucket × slot decomposition for hand/deck/discard counts.
    E2 fix: count info via count_proj only — do NOT double-amplify by
    multiplying tok by counts (high-count cards would dominate)."""

    def __init__(
        self,
        n_card_slots: int = OBS_MAX_CARD_TYPES,
        n_buckets: int = OBS_HAND_BUCKETS,
        d_model: int = 64,
    ) -> None:
        super().__init__()
        self.n_card_slots = n_card_slots
        self.n_buckets = n_buckets
        self.d_model = d_model
        self.bucket_emb = nn.Embedding(n_buckets, d_model)
        self.slot_emb = nn.Embedding(n_card_slots, d_model)
        self.count_proj = nn.Linear(1, d_model)
        self.enemy_size_proj = nn.Linear(OBS_ENEMY_SIZES, d_model)

    def forward(self, card_buckets, enemy_sizes):
        B = card_buckets.shape[0]
        device = card_buckets.device
        bucket_ids = torch.arange(self.n_buckets, device=device)
        slot_ids = torch.arange(self.n_card_slots, device=device)
        b_e = self.bucket_emb(bucket_ids).unsqueeze(1)
        s_e = self.slot_emb(slot_ids).unsqueeze(0)
        tok = (b_e + s_e).unsqueeze(0)
        counts = card_buckets.unsqueeze(-1)
        count_emb = self.count_proj(counts)
        tok_emb = tok + count_emb
        flat = tok_emb.reshape(B, self.n_buckets * self.n_card_slots, self.d_model)
        mask = (card_buckets.reshape(B, -1) > 0).float().unsqueeze(-1)
        flat = flat * mask
        denom = mask.sum(dim=1).clamp(min=1.0)
        pooled = flat.sum(dim=1) / denom
        pooled = pooled + self.enemy_size_proj(enemy_sizes)
        return pooled


class CrossAttentionBlock(nn.Module):
    """Bidirectional counter ⟷ hook cross-attention with NaN-guard +
    LayerNorm pre/post residual."""

    def __init__(self, d_model: int = 64, n_heads: int = 4, dropout: float = 0.1) -> None:
        super().__init__()
        self.counter_to_hook = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.hook_to_counter = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.attn_drop_c2h = nn.Dropout(dropout)
        self.attn_drop_h2c = nn.Dropout(dropout)
        self.counter_ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model),
            nn.Dropout(dropout),
        )
        self.hook_ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model),
            nn.Dropout(dropout),
        )
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.norm3 = nn.LayerNorm(d_model)
        self.norm4 = nn.LayerNorm(d_model)

    def forward(self, counter_emb, hook_emb, counter_mask=None, hook_mask=None):
        hook_kp = ~hook_mask if hook_mask is not None else None
        counter_kp = ~counter_mask if counter_mask is not None else None
        has_hooks = hook_mask.any() if hook_mask is not None else True
        has_counters = counter_mask.any() if counter_mask is not None else True

        if has_hooks:
            attn_out, _ = self.counter_to_hook(counter_emb, hook_emb, hook_emb, key_padding_mask=hook_kp)
            attn_out = torch.nan_to_num(attn_out, 0.0)
            counter_emb = self.norm1(counter_emb + self.attn_drop_c2h(attn_out))
        else:
            counter_emb = self.norm1(counter_emb)
        counter_emb = self.norm2(counter_emb + self.counter_ffn(counter_emb))

        if has_hooks and has_counters:
            attn_out2, _ = self.hook_to_counter(hook_emb, counter_emb, counter_emb, key_padding_mask=counter_kp)
            attn_out2 = torch.nan_to_num(attn_out2, 0.0)
            hook_emb = self.norm3(hook_emb + self.attn_drop_h2c(attn_out2))
        else:
            hook_emb = self.norm3(hook_emb)
        hook_emb = self.norm4(hook_emb + self.hook_ffn(hook_emb))
        return counter_emb, hook_emb
