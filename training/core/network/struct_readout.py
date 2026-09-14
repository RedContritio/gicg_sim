"""Direct structural readout for HP, energy, alive, and dice features.

The dedicated pool bypasses the cross-attention path as specified in
``openspec/specs/network-architecture/encoders.md``. AZ, DMC, and PPO
share this block.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from training.core.obs_constants import N_STRUCTURAL


class StructReadoutBlock(nn.Module):
    """Project ``N_STRUCTURAL`` values directly to ``d_model``."""

    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.proj = nn.Linear(N_STRUCTURAL, d_model)

    def forward(self, structural_values: torch.Tensor) -> torch.Tensor:
        return self.proj(structural_values)
