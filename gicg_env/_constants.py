"""Shared module-level constants for gicg_env + the training stack.

Kept as their own module so the mixin files in gicg_env/_engine_*.py
can import without triggering a circular dependency with
gicg_env.engine (which in turn imports the mixins).

This module is the **single source of truth** for engine-pinned
constants — observation schema sizes, action kind enum, phase enum,
dice color count, reward-events field order. ``training/core/
obs_constants.py`` re-exports from here; ``gicg_env.env_obs`` imports
from here. Historically both sides hard-coded parallel copies and
``env_obs`` had a back-reference cycle into ``training.core``."""

DICE_COLOR_COUNT = 8

PHASE_SELECT_ACTIVE = 1
PHASE_ROUND_START = 2
PHASE_ACTION = 3
PHASE_ROUND_END = 4
PHASE_GAME_OVER = 5

STEP_NEED_TARGET = 0
STEP_CONTINUE = 1
STEP_GAME_OVER = 2

ACTION_SKILL = 0
ACTION_CARD = 1
ACTION_SWITCH = 2
ACTION_END_TURN = 3

# ---------------------------------------------------------------------------
# Observation schema constants — MUST stay in sync with
# gicg_engine/observation.go (Go side writes static + dynamic obs layout).
# ---------------------------------------------------------------------------

# Meta header: phase, round, is_my_turn.
OBS_META_SIZE = 3

# Card pool / hand bucket sizing (engine.ObsMaxCardTypes + per-side enemy
# hand scalar count).
OBS_MAX_CARD_TYPES = 80
OBS_HAND_BUCKETS = 4
OBS_ENEMY_SIZES = 2

# Character / skill index caps (engine.ObsMaxChars × ObsMaxSkillsPerChar).
OBS_MAX_CHARS = 6
OBS_MAX_SKILLS_PER_CHAR = 10
OBS_CHAR_SKILL_REFS_SIZE = 2 * OBS_MAX_CHARS * OBS_MAX_SKILLS_PER_CHAR
OBS_CHAR_ELEMENT_SLOTS = 2 * OBS_MAX_CHARS

# ADR-0019 §B.3c typed damage event ring.
OBS_RECENT_DAMAGE_EVENTS = 8
OBS_RECENT_DAMAGE_FIELD_COUNT = 11
OBS_RECENT_DAMAGE_SLOTS = OBS_RECENT_DAMAGE_EVENTS * OBS_RECENT_DAMAGE_FIELD_COUNT  # 88

# Prepare-skill segment (2 players × (char_idx, skill_slot)).
OBS_PREPARE_SKILL_SLOTS = 2 * 2  # 4

# ADR-0019 §B.2 typed Modifier log per-event slot block.
OBS_MODIFIER_LOG_K_MOD = 4
OBS_MODIFIER_LOG_FIELD_COUNT = 5
OBS_MODIFIER_LOG_SLOTS = OBS_RECENT_DAMAGE_EVENTS * OBS_MODIFIER_LOG_K_MOD * OBS_MODIFIER_LOG_FIELD_COUNT  # 160

# Counter slot total — engine.obsCounterSlots(): 2 players × ObsMaxChars × 128
# per-char + 2 players × 140 per-player + 16 global.
OBS_COUNTER_SLOTS = 2 * OBS_MAX_CHARS * 128 + 2 * 140 + 16  # 1832

# Hand bucket block size (cards × buckets + enemy-hand scalars).
OBS_HAND_BLOCK_SIZE = OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES + OBS_ENEMY_SIZES

# Structural counter sid count — pinned to interp.StructuralCount.
N_STRUCTURAL = 2 * OBS_MAX_CHARS * 4 + 2 * 8 + 2

# RewardEvents field layout — MUST stay in sync with
# gicg_engine/reward_events.go :: RewardEvents struct + capi_reward.go
# :: GameGetRewardEvents slot assignments. Reordering or inserting a
# field in Go breaks the ABI; this enum is the single Python-side
# source of truth so call sites index by name instead of a magic int.
REWARD_EVENTS_FIELDS = (
    'damage_dealt',
    'damage_received',
    'heal_done',
    'enemy_heal_done',
    'shield_absorbed',
    'damage_blocked',
    'kills',
    'total_kills',
    'deaths',
    'total_deaths',
    'reactions_triggered',
    'reactions_received',
    'ap_wasted',
    'energy_overflow',
)
REWARD_EVENTS_COUNT = len(REWARD_EVENTS_FIELDS)
