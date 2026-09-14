"""Re-export of engine-pinned constants from gicg_env.

Single source of truth lives in ``gicg_env._constants`` and is re-
exported via ``gicg_env`` public surface(W1-T1 single-source + B2
public export consolidation)。 This module exists to preserve the
existing import surface ``from training.core.obs_constants import
OBS_*`` used by ~25 callers across training/ + tools/, and to host
paradigm-agnostic helpers (``pick_device``) that are conceptually
adjacent but not engine-pinned。
"""

from __future__ import annotations

import torch

from gicg_env import (
    ACTION_CARD,
    ACTION_END_TURN,
    ACTION_SKILL,
    ACTION_SWITCH,
    ACTION_TUNE,
    ACTION_REROLL,
    DICE_COLOR_COUNT,
    N_STRUCTURAL,
    OBS_CHAR_ELEMENT_SLOTS,
    OBS_DEFINITION_LINK_SLOTS,
    OBS_DEFINITION_LINK_SCHEMA_VERSION,
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_COUNTER_SLOTS,
    OBS_ENEMY_SIZES,
    OBS_HAND_BLOCK_SIZE,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_MAX_DEFINITION_LINKS,
    OBS_MAX_CHARS,
    OBS_MAX_SKILLS_PER_CHAR,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_FIELD_COUNT,
    OBS_MODIFIER_LOG_K_MOD,
    OBS_MODIFIER_LOG_SLOTS,
    OBS_BUFF_ROWS,
    OBS_BUFF_FIELDS,
    OBS_BUFF_SLOTS,
    OBS_PREPARE_SKILL_SLOTS,
    OBS_RECENT_DAMAGE_EVENTS,
    OBS_RECENT_DAMAGE_FIELD_COUNT,
    OBS_RECENT_DAMAGE_SLOTS,
)

__all__ = [
    'ACTION_CARD',
    'ACTION_END_TURN',
    'ACTION_SKILL',
    'ACTION_SWITCH',
    'ACTION_TUNE',
    'ACTION_REROLL',
    'DICE_COLOR_COUNT',
    'N_STRUCTURAL',
    'OBS_CHAR_ELEMENT_SLOTS',
    'OBS_DEFINITION_LINK_SLOTS',
    'OBS_DEFINITION_LINK_SCHEMA_VERSION',
    'OBS_CHAR_SKILL_REFS_SIZE',
    'OBS_COUNTER_SLOTS',
    'OBS_ENEMY_SIZES',
    'OBS_HAND_BLOCK_SIZE',
    'OBS_HAND_BUCKETS',
    'OBS_MAX_CARD_TYPES',
    'OBS_MAX_DEFINITION_LINKS',
    'OBS_MAX_CHARS',
    'OBS_MAX_SKILLS_PER_CHAR',
    'OBS_META_SIZE',
    'OBS_MODIFIER_LOG_FIELD_COUNT',
    'OBS_MODIFIER_LOG_K_MOD',
    'OBS_MODIFIER_LOG_SLOTS',
    'OBS_BUFF_ROWS',
    'OBS_BUFF_FIELDS',
    'OBS_BUFF_SLOTS',
    'OBS_PREPARE_SKILL_SLOTS',
    'OBS_RECENT_DAMAGE_EVENTS',
    'OBS_RECENT_DAMAGE_FIELD_COUNT',
    'OBS_RECENT_DAMAGE_SLOTS',
    'pick_device',
]


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
