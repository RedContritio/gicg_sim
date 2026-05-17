"""Struct readout block — C1v7 fix for cross-attention 零空间.

memory ref: project_c1v7_success — pool zero-space C18 theorem; this
block reads structural counters directly from struct_feat (HP/energy/
alive/dice) and feeds them as a dedicated pool slot, sidestepping the
attention saturation pathology.

Paradigm-agnostic: AZ + DMC + PPO all use the same struct readout.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from training.core.obs_constants import N_STRUCTURAL


class StructReadoutBlock(nn.Module):
    """Linear projection of N_STRUCTURAL → d_model. Bypass for the
    cross-attention zero-space C1v7 found in 2026-04 reviews."""

    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.proj = nn.Linear(N_STRUCTURAL, d_model)

    def forward(self, structural_values: torch.Tensor) -> torch.Tensor:
        return self.proj(structural_values)
