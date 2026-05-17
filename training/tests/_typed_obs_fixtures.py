"""Shared fixture helpers for typed obs padding (Round-6 S-3).

Multiple test files need to construct padded recent_damage / modifier_log
tensors that match engine encode_*_padding output (categorical=-2,
scalar=0). Centralize so all tests exercise the same production
padding convention rather than each rolling its own (zero-padded
fixtures was the gap Round-5 S2 found in test_train + test_buffer,
Round-6 S-3 found the same gap in test_network_az_*).
"""

from __future__ import annotations

import numpy as np
import torch


def make_recent_damage_padding_np(K: int = 8) -> np.ndarray:
    """Padded recent_damage matching engine encodeRecentDamageEvents:
    categorical fields (0/1/2/3/4/10) = -2, scalar (5/6/7/8/9) = 0."""
    rd = np.zeros((K, 11), dtype=np.float32)
    for fi in (0, 1, 2, 3, 4, 10):
        rd[..., fi] = -2
    return rd


def make_modifier_log_padding_np(K: int = 8, K_mod: int = 4) -> np.ndarray:
    """Padded modifier_log: categorical (0/3/4) = -2, scalar (1/2) = 0."""
    ml = np.zeros((K, K_mod, 5), dtype=np.float32)
    for fi in (0, 3, 4):
        ml[..., fi] = -2
    return ml


def make_recent_damage_padding_torch(B: int = 1, K: int = 8) -> torch.Tensor:
    rd = torch.zeros(B, K, 11)
    for fi in (0, 1, 2, 3, 4, 10):
        rd[..., fi] = -2
    return rd


def make_modifier_log_padding_torch(B: int = 1, K: int = 8, K_mod: int = 4) -> torch.Tensor:
    ml = torch.zeros(B, K, K_mod, 5)
    for fi in (0, 3, 4):
        ml[..., fi] = -2
    return ml


def make_prepare_skill_padding_torch(B: int = 1) -> torch.Tensor:
    """prepare_skill keeps -1 = "no prepare" real (encodePrepareSkill convention)."""
    return torch.full((B, 2, 2), -1.0)
