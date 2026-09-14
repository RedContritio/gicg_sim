"""gicg_env — Python binding for the Go gicg engine.

Public surface:
- ``GicgEngine`` + ``GicgEnv`` — lazily loaded via PEP 562 module
  ``__getattr__`` so importing constants alone does NOT trigger
  ``ctypes.CDLL(libgicg.dylib)``. This preserves the DMC master-process
  invariant: the orchestrator may import observation constants, but cgo
  state is loaded only in spawned subprocesses (see
  ``training/paradigms/dmc/tests/test_go_subprocess_5ep_e2e.py``).
- Engine-pinned constants (action / phase / step / dice / obs / reward
  events) — eagerly re-exported from ``gicg_env._constants``, which has
  no libgicg dependency. External callers should import these names from
  ``gicg_env`` rather than the private ``_constants`` module.
"""

from typing import TYPE_CHECKING

from gicg_env._constants import (
    ACTION_CARD,
    ACTION_END_TURN,
    ACTION_SKILL,
    ACTION_SWITCH,
    ACTION_TUNE,
    ACTION_REROLL,
    DICE_COLOR_COUNT,
    N_STRUCTURAL,
    OBS_CHAR_ELEMENT_SLOTS,
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_DEFINITION_LINK_SLOTS,
    OBS_DEFINITION_LINK_SCHEMA_VERSION,
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
    PHASE_ACTION,
    PHASE_GAME_OVER,
    PHASE_ROUND_END,
    PHASE_ROUND_START,
    PHASE_SELECT_ACTIVE,
    REWARD_EVENTS_COUNT,
    REWARD_EVENTS_FIELDS,
    STEP_CONTINUE,
    STEP_GAME_OVER,
    STEP_NEED_TARGET,
)

if TYPE_CHECKING:  # pragma: no cover — type-checker only
    from .engine import GicgEngine
    from .env import GicgEnv

__all__ = [
    # Lazy-loaded entry points (require libgicg)
    'GicgEngine',
    'GicgEnv',
    # Engine-pinned constants (no libgicg load)
    'ACTION_CARD',
    'ACTION_END_TURN',
    'ACTION_SKILL',
    'ACTION_SWITCH',
    'ACTION_TUNE',
    'ACTION_REROLL',
    'DICE_COLOR_COUNT',
    'N_STRUCTURAL',
    'OBS_CHAR_ELEMENT_SLOTS',
    'OBS_CHAR_SKILL_REFS_SIZE',
    'OBS_DEFINITION_LINK_SLOTS',
    'OBS_DEFINITION_LINK_SCHEMA_VERSION',
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
    'PHASE_ACTION',
    'PHASE_GAME_OVER',
    'PHASE_ROUND_END',
    'PHASE_ROUND_START',
    'PHASE_SELECT_ACTIVE',
    'REWARD_EVENTS_COUNT',
    'REWARD_EVENTS_FIELDS',
    'STEP_CONTINUE',
    'STEP_GAME_OVER',
    'STEP_NEED_TARGET',
]


def __getattr__(name: str):
    if name == 'GicgEngine':
        from .engine import GicgEngine

        return GicgEngine
    if name == 'GicgEnv':
        from .env import GicgEnv

        return GicgEnv
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
