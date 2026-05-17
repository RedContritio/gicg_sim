"""Observation / action constants — paradigm-agnostic.

Copied from training/framework/obs_constants.py (engine-pinned values).
``pick_device`` lives here for backward-compat with framework callers.
"""

from __future__ import annotations

import torch


def pick_device() -> torch.device:
    """Project default device picker. Prefers MPS / CUDA / CPU.

    Note (memory feedback_default_mps): MPS slower than CPU for
    d_model=128 + small batch — callers should override based on
    measured throughput rather than blindly trust this default."""
    if torch.backends.mps.is_available():
        return torch.device('mps')
    if torch.cuda.is_available():
        return torch.device('cuda')
    return torch.device('cpu')


# Action kind enum (matches gicg_env/engine.py).
ACTION_SKILL = 0
ACTION_CARD = 1
ACTION_SWITCH = 2
ACTION_END_TURN = 3

# Matches gicg_env/engine.DICE_COLOR_COUNT.
DICE_COLOR_COUNT = 8

# Matches gicg_engine/observation.go.
OBS_META_SIZE = 3
OBS_MAX_CARD_TYPES = 80
OBS_HAND_BUCKETS = 4
OBS_ENEMY_SIZES = 2
OBS_MAX_CHARS = 6
OBS_MAX_SKILLS_PER_CHAR = 10
OBS_CHAR_SKILL_REFS_SIZE = 2 * OBS_MAX_CHARS * OBS_MAX_SKILLS_PER_CHAR
OBS_CHAR_ELEMENT_SLOTS = 2 * OBS_MAX_CHARS

# ADR-0019 §B.3c — typed damage event ring + prepare-skill segment.
OBS_RECENT_DAMAGE_EVENTS = 8
OBS_RECENT_DAMAGE_FIELD_COUNT = 11
OBS_RECENT_DAMAGE_SLOTS = OBS_RECENT_DAMAGE_EVENTS * OBS_RECENT_DAMAGE_FIELD_COUNT  # 88
OBS_PREPARE_SKILL_SLOTS = 2 * 2  # 4

# ADR-0019 §B.2 — typed Modifier log per-event slot block.
OBS_MODIFIER_LOG_K_MOD = 4
OBS_MODIFIER_LOG_FIELD_COUNT = 5
OBS_MODIFIER_LOG_SLOTS = OBS_RECENT_DAMAGE_EVENTS * OBS_MODIFIER_LOG_K_MOD * OBS_MODIFIER_LOG_FIELD_COUNT  # 160

# Structural counter sid count — pinned to interp.StructuralCount.
N_STRUCTURAL = 2 * OBS_MAX_CHARS * 4 + 2 * 8 + 2
