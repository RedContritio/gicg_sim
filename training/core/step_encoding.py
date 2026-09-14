"""Pure NumPy helpers for fixed-shape step observations and action metadata."""

from __future__ import annotations

import numpy as np

from training.core.obs_constants import (
    ACTION_END_TURN,
    DICE_COLOR_COUNT,
    OBS_ENEMY_SIZES,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_FIELD_COUNT,
    OBS_MODIFIER_LOG_K_MOD,
    OBS_MODIFIER_LOG_SLOTS,
    OBS_PREPARE_SKILL_SLOTS,
    OBS_RECENT_DAMAGE_EVENTS,
    OBS_RECENT_DAMAGE_FIELD_COUNT,
    OBS_RECENT_DAMAGE_SLOTS,
)


def pad_action_refs(refs_np: np.ndarray, max_actions: int) -> np.ndarray:
    padded = np.full((max_actions, 3), -1, dtype=np.int64)
    padded[:, 0] = ACTION_END_TURN
    n = min(len(refs_np), max_actions)
    if n > 0:
        padded[:n] = np.asarray(refs_np[:n], dtype=np.int64)
    return padded


def pad_action_payments(payments_np: np.ndarray, max_actions: int) -> np.ndarray:
    padded = np.zeros((max_actions, DICE_COLOR_COUNT), dtype=np.float32)
    n = min(len(payments_np), max_actions)
    if n > 0:
        padded[:n] = np.asarray(payments_np[:n], dtype=np.float32)
    return padded


def parse_dynamic_np(dyn_obs, n_counter_slots, *, copy=True):
    """Parse a normalized dynamic obs vector → (counter_values, meta, card_buckets, enemy_sizes)."""
    meta = dyn_obs[:OBS_META_SIZE].astype(np.float32, copy=copy)
    c_end = OBS_META_SIZE + n_counter_slots
    counter_values = dyn_obs[OBS_META_SIZE:c_end].astype(np.float32, copy=copy)
    hand_end = c_end + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
    card_buckets = dyn_obs[c_end:hand_end].astype(np.float32, copy=copy).reshape(OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
    enemy_sizes = dyn_obs[hand_end : hand_end + OBS_ENEMY_SIZES].astype(np.float32, copy=copy)
    return counter_values, meta, card_buckets, enemy_sizes


def typed_segment_offsets(n_counter_slots: int) -> dict:
    """Single source of truth for typed obs segment offsets."""
    c_end = OBS_META_SIZE + n_counter_slots
    hand_end = c_end + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
    enemy_end = hand_end + OBS_ENEMY_SIZES
    rd_end = enemy_end + OBS_RECENT_DAMAGE_SLOTS
    ps_end = rd_end + OBS_PREPARE_SKILL_SLOTS
    ml_end = ps_end + OBS_MODIFIER_LOG_SLOTS
    return {'enemy_end': enemy_end, 'rd_end': rd_end, 'ps_end': ps_end, 'ml_end': ml_end}


def parse_dynamic_typed_np(dyn_obs, n_counter_slots, *, copy=True, include_modifier_log=False):
    """Extract typed segments (recent_damage, prepare_skill, [modifier_log])."""
    off = typed_segment_offsets(n_counter_slots)
    enemy_end = off['enemy_end']
    rd_end = off['rd_end']
    ps_end = off['ps_end']
    ml_end = off['ml_end']
    recent_damage = (
        dyn_obs[enemy_end:rd_end]
        .astype(np.float32, copy=copy)
        .reshape(OBS_RECENT_DAMAGE_EVENTS, OBS_RECENT_DAMAGE_FIELD_COUNT)
    )
    prepare_skill = dyn_obs[rd_end:ps_end].astype(np.float32, copy=copy).reshape(2, 2)
    if not include_modifier_log:
        return recent_damage, prepare_skill
    if len(dyn_obs) < ml_end:
        raise ValueError(
            f'parse_dynamic_typed_np: dyn_obs len={len(dyn_obs)} < ml_end={ml_end}; modifier_log segment absent'
        )
    modifier_log = (
        dyn_obs[ps_end:ml_end]
        .astype(np.float32, copy=copy)
        .reshape(OBS_RECENT_DAMAGE_EVENTS, OBS_MODIFIER_LOG_K_MOD, OBS_MODIFIER_LOG_FIELD_COUNT)
    )
    return recent_damage, prepare_skill, modifier_log


def build_legal_mask(max_actions: int, n_legal: int) -> np.ndarray:
    mask = np.zeros(max_actions, dtype=bool)
    mask[:n_legal] = True
    return mask


def parse_buffs_np(dyn_obs, n_counter_slots, *, copy=True):
    """Parse the versioned tail, retaining only live rows (one padding row if empty)."""
    from training.core.obs_constants import OBS_BUFF_ROWS, OBS_BUFF_FIELDS, OBS_BUFF_SLOTS

    start = typed_segment_offsets(n_counter_slots)['ml_end']
    if len(dyn_obs) == start:  # old hand-built fixtures only; GicgEnv rejects old ABI
        return np.zeros((1, OBS_BUFF_FIELDS), dtype=np.float32)
    if len(dyn_obs) != start + OBS_BUFF_SLOTS:
        raise ValueError('unsupported buff observation layout')
    rows = np.asarray(dyn_obs[start:], dtype=np.float32).reshape(OBS_BUFF_ROWS, OBS_BUFF_FIELDS)
    live = np.flatnonzero(rows[:, 0])
    rows = rows[: int(live[-1]) + 1 if len(live) else 1]
    return rows.copy() if copy else rows


def pad_buffs_np(instances):
    """Pad a batch to its longest live effect sequence, not the wire capacity."""
    from training.core.obs_constants import OBS_BUFF_FIELDS

    if not instances:
        raise ValueError('empty buff batch')
    longest = max(1, max(len(rows) for rows in instances))
    out = np.zeros((len(instances), longest, OBS_BUFF_FIELDS), dtype=np.float32)
    for i, rows in enumerate(instances):
        rows = np.asarray(rows)
        if rows.ndim != 2 or rows.shape[1] != OBS_BUFF_FIELDS:
            raise ValueError('invalid buff row layout')
        out[i, : len(rows)] = rows
    return out
