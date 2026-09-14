"""Fuse live ordered effect instances with the shared static rule embeddings."""

import torch
from torch import nn

from training.core.obs_constants import OBS_BUFF_FIELDS, OBS_BUFF_ROWS


class BuffEncoder(nn.Module):
    def __init__(self, d_model, source_embedding=None):
        super().__init__()
        self.kind = nn.Embedding(7, d_model)
        self.source = source_embedding if source_embedding is not None else nn.Embedding(2000, d_model)
        self.target_owner = nn.Embedding(3, d_model)
        self.target_character = nn.Embedding(7, d_model)
        self.owner = nn.Embedding(3, d_model)
        self.character = nn.Embedding(7, d_model)
        self.trigger = nn.Embedding(64, d_model)
        self.order = nn.Embedding(OBS_BUFF_ROWS, d_model)
        self.state = nn.Linear(6 * 9, d_model)
        self.attention = nn.MultiheadAttention(d_model, 4, batch_first=True)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, rows, hooks, source_features=None, return_tokens=False):
        if rows is None:
            pooled = hooks.new_zeros((hooks.shape[0], hooks.shape[-1]))
            return (pooled, None) if return_tokens else pooled
        if rows.ndim != 3 or rows.shape[-1] != OBS_BUFF_FIELDS:
            raise ValueError('invalid buff observation shape')
        valid = rows[..., 0] > 0
        refs = rows[..., 7].long()
        if ((refs < -1) & valid).any() or ((refs >= hooks.shape[1]) & valid).any():
            raise ValueError('buff refers to missing rule hook')
        rule = hooks.gather(1, refs.clamp(0, hooks.shape[1] - 1).unsqueeze(-1).expand(-1, -1, hooks.shape[-1]))
        rule = rule * (refs >= 0).unsqueeze(-1)
        source = rows[..., 13].long()
        kinds = rows[..., 12].long()
        if (((source < -1) | (source >= self.source.num_embeddings) | (kinds < 0) | (kinds > 6)) & valid).any():
            raise ValueError('invalid entity binding')
        binding = self.source(source.clamp(0, self.source.num_embeddings - 1)) * (source >= 0).unsqueeze(-1)
        if source_features is not None:
            if source_features.shape != binding.shape:
                raise ValueError('invalid semantic entity source shape')
            binding = source_features
        # Numeric mechanics are quantities, not categorical card/name IDs.
        numeric = rows[..., [3, 4, 5, 9, 10, 11]]
        # Preserve magnitude while resolving nearby values before pooling.
        # Fixed multi-scale features encode quantities, never card-specific
        # thresholds or trigger answers. The log branch breaks periodic ties.
        phase = numeric.unsqueeze(-1) * numeric.new_tensor([torch.pi, torch.pi / 2, torch.pi / 4, torch.pi / 8])
        magnitude = numeric.sign() * numeric.abs().log1p()
        numeric = torch.cat((magnitude.unsqueeze(-1), phase.sin(), phase.cos()), dim=-1).flatten(-2)
        tokens = (
            rule
            + binding
            + self.kind(kinds.clamp(0, 6))
            + self.target_owner((rows[..., 14].long() + 1).clamp(0, 2))
            + self.target_character((rows[..., 15].long() + 1).clamp(0, 6))
            + self.owner((rows[..., 1].long() + 1).clamp(0, 2))
            + self.character((rows[..., 2].long() + 1).clamp(0, 6))
            + self.trigger(rows[..., 8].long().clamp(0, 63))
            + self.order(rows[..., 6].long().clamp(0, OBS_BUFF_ROWS - 1))
            + self.state(numeric)
        )
        tokens = tokens * valid.unsqueeze(-1)
        safe = valid.clone()
        safe[:, 0] = True  # all-padding batches must not generate NaNs
        attended, _ = self.attention(tokens, tokens, tokens, key_padding_mask=~safe, need_weights=False)
        tokens = self.norm(tokens + attended) * valid.unsqueeze(-1)
        pooled = tokens.sum(1) / valid.sum(1, keepdim=True).clamp_min(1)
        return (pooled, tokens) if return_tokens else pooled
