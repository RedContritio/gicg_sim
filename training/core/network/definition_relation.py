"""Definition-to-effect incidence for canonical skill and card hooks."""

from __future__ import annotations

import torch
from torch import nn


class DefinitionRelation(nn.Module):
    """Add referenced effect features to canonical definition hooks."""

    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.message = nn.Sequential(nn.Linear(2 * d_model, d_model), nn.ReLU(), nn.Linear(d_model, d_model))
        self.norm = nn.LayerNorm(d_model)

    def forward(self, hooks: torch.Tensor, links: torch.Tensor) -> torch.Tensor:
        if links.ndim != 3 or links.shape[-1] != 2:
            raise ValueError(f'definition_links must have shape (B, E, 2), got {tuple(links.shape)}')
        if links.shape[0] != hooks.shape[0]:
            raise ValueError('definition_links batch does not match hook embeddings')
        n_hooks = hooks.shape[1]
        if (links < -1).any() or ((links[..., 0] >= 0) ^ (links[..., 1] >= 0)).any():
            raise ValueError('definition link rows must contain two active indices or (-1, -1) padding')
        valid = (links[..., 0] >= 0) & (links[..., 1] >= 0)
        if ((links >= n_hooks) & valid.unsqueeze(-1)).any():
            raise ValueError('definition link references a hook outside the active layout')
        source = links[..., 0].clamp(0, max(n_hooks - 1, 0))
        effect = links[..., 1].clamp(0, max(n_hooks - 1, 0))
        gather_shape = (-1, -1, hooks.shape[-1])
        source_hook = hooks.gather(1, source.unsqueeze(-1).expand(*gather_shape))
        effect_hook = hooks.gather(1, effect.unsqueeze(-1).expand(*gather_shape))
        messages = self.message(torch.cat((source_hook, effect_hook), dim=-1))
        messages = messages * valid.unsqueeze(-1)
        summed = torch.zeros_like(hooks)
        counts = hooks.new_zeros((hooks.shape[0], n_hooks, 1))
        summed.scatter_add_(1, source.unsqueeze(-1).expand_as(messages), messages)
        counts.scatter_add_(1, source.unsqueeze(-1), valid.unsqueeze(-1).to(hooks.dtype))
        return self.norm(hooks + summed / counts.clamp_min(1))
