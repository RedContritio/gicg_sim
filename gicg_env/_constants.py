"""Shared module-level constants for gicg_env.engine + its mixins.

Kept as their own module so the mixin files in gicg_env/_engine_*.py
can import without triggering a circular dependency with
gicg_env.engine (which in turn imports the mixins). The public
entry-point gicg_env.engine re-exports these so external callers'
``from gicg_env.engine import DICE_COLOR_COUNT`` still works."""

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
