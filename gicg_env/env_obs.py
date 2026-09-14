"""Observation-normalization mixin for GicgEnv.

Owns the _get_obs() implementation and re-exports the obs-layout
constants that describe the static/dynamic obs buffers written by the
Go side. Constants now live in ``gicg_env._constants`` (single source
of truth post W1-T1); imported here so legacy callers' ``from
gicg_env.env_obs import OBS_COUNTER_SLOTS`` (and ``gicg_env.env``
re-export chain) keep resolving. Pre W1-T1: env_obs.py hard-coded a
parallel copy and back-referenced ``training.core.obs_constants``,
forming a cycle."""

from __future__ import annotations

import numpy as np

from gicg_env._constants import (
    OBS_COUNTER_SLOTS,
    OBS_ENEMY_SIZES,
    OBS_HAND_BLOCK_SIZE,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_SLOTS,
    OBS_PREPARE_SKILL_SLOTS,
    OBS_RECENT_DAMAGE_SLOTS,
)

__all__ = [
    'OBS_COUNTER_SLOTS',
    'OBS_ENEMY_SIZES',
    'OBS_HAND_BLOCK_SIZE',
    'OBS_HAND_BUCKETS',
    'OBS_MAX_CARD_TYPES',
    'OBS_META_SIZE',
    'OBS_MODIFIER_LOG_SLOTS',
    'OBS_PREPARE_SKILL_SLOTS',
    'OBS_RECENT_DAMAGE_SLOTS',
    '_ObsMixin',
    'compute_mask_slots',
]


def compute_mask_slots(obs_mask, labels):
    """Pre-compute per-perspective obs slot index arrays for a mask spec.

    Returns a 2-element list ``[p0_slots, p1_slots]``; for obs built from
    perspective P, ``_get_obs`` zeros ``out[p_slots]``. Per-perspective
    because the enemy changes, while counter slot identity stays fixed in
    the same canonical P0/P1 layout as static min/max/SID metadata.

    Accepted categories (``obs_mask`` is a list of str):
    - ``"enemy_dice"``: zero all enemy dice_* PerPlayer counter slots
    """
    if not obs_mask:
        return None
    categories = set(obs_mask)
    per_persp: list[list[int]] = [[], []]
    for slot, label in enumerate(labels):
        if ':' not in label:
            continue
        pfx = label.split(':', 1)[0]
        if pfx not in ('P0', 'P1'):
            continue
        player = int(pfx[1])
        for persp in (0, 1):
            enemy = 1 - persp
            if player != enemy:
                continue
            if 'enemy_dice' in categories and 'dice_' in label:
                per_persp[persp].append(OBS_META_SIZE + slot)
    return [np.asarray(p, dtype=np.int64) for p in per_persp]


class _ObsMixin:
    """Normalizes the Go-side raw dynamic obs into the float32 buffer
    the training stack consumes. Expects the host class to expose
    ``_engine``, ``_slot_min``, ``_slot_denom``.

    Optionally masks specified obs slots after normalization — used for
    curriculum partial-observability (Stage 2+). Masking happens in
    Python (not the Go engine) so the engine stays a single reference
    implementation; different stages apply different masks via
    ``_mask_slots_per_perspective`` pre-computed at env construction."""

    def _get_obs(self):
        raw = self._engine.get_dynamic_obs()
        # Layout (gicg_engine/observation.go):
        #   [0:3]                       meta (phase, round, is_my_turn)
        #   [3:3+OBS_COUNTER_SLOTS]     counter values
        #   [c_end:hand_end]            4×80 card buckets
        #   [hand_end:enemy_end]        2 enemy sizes
        # ADR-0019 typed segments (cast to float, NO normalization —
        # they are typed integer fields, network embedders own the scale):
        #   [enemy_end:rd_end]          recent damage events (K=8 × 11)
        #   [rd_end:ps_end]             prepare-skill (2 player × 2)
        #   [ps_end:ml_end]             modifier log (K=8 × K_mod=4 × 5)
        out = np.empty_like(raw, dtype=np.float32)
        out[:OBS_META_SIZE] = raw[:OBS_META_SIZE]  # meta stays as-is
        c_start = OBS_META_SIZE
        c_end = c_start + OBS_COUNTER_SLOTS
        out[c_start:c_end] = (raw[c_start:c_end].astype(np.float32) - self._slot_min) / self._slot_denom
        # Card block: divide counts by a fixed ceiling so the scale is
        # invariant across steps (counter-normalization would over-scale
        # buckets with small active card diversity).
        # Round-4 S-2: 用 import 的 OBS_HAND_BUCKETS / OBS_ENEMY_SIZES,
        # 不再 hardcode 4/2;Python 内部跨文件 drift 由单一 source 兜底。
        hand_start = c_end
        hand_end = hand_start + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
        out[hand_start:hand_end] = raw[hand_start:hand_end].astype(np.float32) / 10.0
        # Enemy hand/deck sizes (2 scalars): divide by a modest ceiling so
        # they map into the same ~[0,1] range.
        enemy_end = hand_end + OBS_ENEMY_SIZES
        out[hand_end:enemy_end] = raw[hand_end:enemy_end].astype(np.float32) / 20.0
        # ADR-0019 typed segments — pass-through float cast. Network
        # consumers parse the raw int fields via dedicated embedders;
        # bulk /20 normalization (the pre-§B.3c default) would conflate
        # distinct typed axes (player_idx vs raw_value etc.).
        out[enemy_end:] = raw[enemy_end:].astype(np.float32)
        # Apply Python-side partial-observability mask. The mask index set
        # depends on current acting_player (obs perspective), so we look
        # up the pre-computed per-perspective slot list.
        mask_sets = getattr(self, '_mask_slots_per_perspective', None)
        if mask_sets is not None:
            slots = mask_sets[self._engine.acting_player]
            if len(slots) > 0:
                out[slots] = 0.0
        return out
