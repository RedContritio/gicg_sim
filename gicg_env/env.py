"""RL Environment wrapper for GICG."""

import numpy as np

from .engine import (
    GicgEngine,
    STEP_NEED_TARGET,
)
from .env_action import _ActionMixin
from .env_obs import (
    OBS_COUNTER_SLOTS,
    OBS_HAND_BLOCK_SIZE,
    OBS_MAX_CARD_TYPES,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_SLOTS,
    OBS_PREPARE_SKILL_SLOTS,
    OBS_RECENT_DAMAGE_SLOTS,
    _ObsMixin,
    compute_mask_slots,
)
from .env_query import _QueryMixin
from .env_reward import RewardShaping, compute_shaped_reward

ALL_CHARS = ['赤蝶', '墨客', '猫咪', '刻师傅', '天星']

# OBS_* re-exported for back-compat with external call sites that do
# ``from gicg_env.env import OBS_COUNTER_SLOTS`` (e.g. tools/sanity_sid_pin).
__all__ = [
    'ALL_CHARS',
    'GicgEnv',
    'OBS_COUNTER_SLOTS',
    'OBS_HAND_BLOCK_SIZE',
    'OBS_MAX_CARD_TYPES',
    'OBS_META_SIZE',
    'OBS_MODIFIER_LOG_SLOTS',
    'OBS_PREPARE_SKILL_SLOTS',
    'OBS_RECENT_DAMAGE_SLOTS',
    'RewardShaping',
]


def _terminal_z(winner: int) -> float:
    """Map the engine's winner code to a P0-perspective outcome.

    +1 if P0 won, -1 if P1 won, 0 for draw (winner == 2). Panics on
    winner == -1 (game not yet terminated) or any unexpected value —
    callers must guard with ``done`` first. The strict raise replaces
    the previous silent "fall through to 0", which would have
    corrupted AZ training targets whenever it was called by mistake.
    """
    if winner == 0:
        return 1.0
    if winner == 1:
        return -1.0
    if winner == 2:
        return 0.0
    raise ValueError(
        f'_terminal_z called with winner={winner} — expected 0/1/2 '
        '(only valid on terminal states; guard the call with env.done)'
    )


class GicgEnv(_ActionMixin, _ObsMixin, _QueryMixin):
    """Self-play environment. Team rosters / card pool fixed at
    construction; reset(seed) starts a fresh game with same ruleset.
    step() → (obs, reward, done, info). Two reward modes:
    ``reward_shaping=None`` (terminal-z mode) → reward=0 every step,
    callers read terminal ``info['z']`` (P0-perspective outcome) at
    game over;``reward_shaping={...}`` (dense-shaping mode) → per-step
    reward from the RewardEvents delta scored by the supplied
    coefficients。 See ``env_reward.py:RewardShaping``。"""

    def __init__(
        self,
        team_0,
        team_1,
        card_pool=None,
        seed=42,
        data_dir=None,
        lib_path=None,
        obs_config=None,
        reward_shaping=None,
        max_rounds=0,
        fix_dice=None,
        obs_mask=None,
        deck_padding=None,
        pool=None,
    ):
        self._engine = GicgEngine(lib_path=lib_path)
        self._team_0 = list(team_0)
        self._team_1 = list(team_1)
        self._card_pool = None if card_pool is None else list(card_pool)
        self._data_dir = data_dir
        # obs_config persists across resets so reset(seed) reconstructs the
        # same obs regime. None = legacy all-on default.
        self._obs_config = None if obs_config is None else dict(obs_config)
        self._reward_shaping = RewardShaping.from_arg(reward_shaping)
        # Static config: set once at construction, not mutated by reset().
        self._max_rounds = int(max_rounds)
        self._fix_dice = None if fix_dice is None else list(fix_dice)
        self._deck_padding = None if deck_padding is None else dict(deck_padding)
        self._pool = pool if (pool is None or isinstance(pool, str)) else list(pool)
        self._engine.new_game(
            players=[self._team_0, self._team_1],
            seed=seed,
            data_dir=data_dir,
            card_pool=self._card_pool,
            obs_config=self._obs_config,
            max_rounds=self._max_rounds,
            fix_dice=self._fix_dice,
            deck_padding=self._deck_padding,
            pool=self._pool,
        )
        self._static_obs_size = self._engine._lib.GameGetStaticObsSize()
        self._dynamic_obs_size = self._engine._lib.GameGetDynamicObsSize()
        self._static_obs = self._engine.get_static_obs()

        # Per-slot (min, max) normalization: the static obs layout
        # writes (min, max, sid) per counter slot at the front. Parse it
        # once so _get_obs can do per-slot normalization without depending
        # on the current step's max feature. Denominator floored to 1.0 so
        # padding slots (min=max=0) and degenerate slots don't divide by 0.
        counter_meta = self._static_obs[: OBS_COUNTER_SLOTS * 3].reshape(OBS_COUNTER_SLOTS, 3)
        self._slot_min = counter_meta[:, 0].astype(np.float32)
        self._slot_max = counter_meta[:, 1].astype(np.float32)
        self._slot_denom = np.maximum(self._slot_max - self._slot_min, 1.0).astype(np.float32)

        # Optional partial-observability mask. obs_mask accepts:
        #   None                 — no masking (default, fully observable)
        #   ["enemy_dice"]       — mask enemy dice_* counter slots
        #   ["enemy_dice", "enemy_hand_size"] — composable presets
        # Pre-compute per-perspective slot index arrays so _get_obs is O(n).
        labels = self._engine.get_active_counter_slot_labels()
        self._mask_slots_per_perspective = compute_mask_slots(obs_mask=obs_mask, labels=labels)

    def reset(self, seed=42, deck_seeds=None):
        """Restart with the same teams and card pool. Cheap — no DSL reload.

        review D.5 (2026-05-14): optional 3-axis seed split. seed controls
        dice rolls + DSL randomness + obs perm (same as before); deck_seeds
        = (deck_seed_p0, deck_seed_p1) optionally overrides per-player deck
        Fisher-Yates shuffle. Default deck_seeds=None → both fall back to
        seed (backward compat with single-seed callers)."""
        if deck_seeds is None:
            self._engine.reset_dynamic(seed)
        else:
            self._engine.reset_dynamic_with_seeds(seed, deck_seeds[0], deck_seeds[1])
        return self._get_obs()

    def clone(self):
        """Return a deep-copied env that can be stepped independently. Useful
        for speculative rollouts. The clone shares the static ruleset."""
        twin = GicgEnv.__new__(GicgEnv)
        twin._engine = self._engine.clone()
        twin._team_0 = list(self._team_0)
        twin._team_1 = list(self._team_1)
        twin._card_pool = None if self._card_pool is None else list(self._card_pool)
        twin._data_dir = self._data_dir
        twin._static_obs_size = self._static_obs_size
        twin._dynamic_obs_size = self._dynamic_obs_size
        twin._static_obs = self._static_obs
        twin._slot_min = self._slot_min
        twin._slot_max = self._slot_max
        twin._slot_denom = self._slot_denom
        # RewardShaping is a frozen dataclass (or None) — shared by
        # reference is safe; the clone scores its own events without
        # affecting this env's reward accounting.
        twin._reward_shaping = self._reward_shaping
        twin._max_rounds = self._max_rounds
        twin._fix_dice = self._fix_dice
        twin._deck_padding = None if self._deck_padding is None else dict(self._deck_padding)
        twin._pool = self._pool if (self._pool is None or isinstance(self._pool, str)) else list(self._pool)
        twin._mask_slots_per_perspective = self._mask_slots_per_perspective
        return twin

    def step(self, action_idx):
        """Take an action. Standard RL 4-tuple return.

        Args:
            action_idx: index into the legal actions array. The semantics
                depend on what get_legal_actions() returns *now* — could be
                a regular skill/card/switch/end_turn, OR an initial active
                char selection (PhaseSelectActive), OR a target choice
                (after a card play left a pending target). The env routes
                each to the correct engine call automatically.

        Returns:
            obs:    observation for the next player to act (zeros on terminal)
            reward: scalar from the POV of the player who was acting
                    *before* this step call. 0.0 when ``reward_shaping=None``;
                    else computed from per-player RewardEvents delta via
                    the configured RewardShaping coefs. See the class
                    docstring for the two modes.
            done:   whether the game is over
            info:   dict with at least ``winner`` and ``turn``. On terminal
                    steps also carries ``z``, the P0-perspective outcome
                    (+1 P0 wins, -1 P1 wins, 0 draw). On intermediate steps
                    also carries ``need_target=True`` if the action just
                    played left a pending target choice (the next call to
                    step() will route to the target resolver).
        """
        # Snapshot the acting player's RewardEvents *before* the step so
        # we can diff after. Skipping the read entirely when shaping is
        # disabled avoids a cgo round-trip on the terminal-z hot path.
        me = self._engine.acting_player
        events_before = self._engine.get_reward_events(me) if self._reward_shaping is not None else None

        # Dispatch: if the engine is currently in a pending state (card
        # target needed or forced switch pending), route to step_target;
        # otherwise, regular step. We query the engine directly rather
        # than tracking a local flag, so the routing is correct across
        # snapshot / restore cycles.
        if self._engine.has_pending:
            result = self._engine.step_target(action_idx)
        else:
            result = self._engine.step(action_idx)

        if result == STEP_NEED_TARGET:
            reward = self._score_reward(events_before, me, done=False)
            return (
                self._get_obs(),
                reward,
                False,
                {
                    'need_target': True,
                    'winner': -1,
                    'turn': self._engine.turn,
                },
            )

        done = self._engine.done
        obs = self._get_obs() if not done else np.zeros(self.obs_size, dtype=np.float32)
        reward = self._score_reward(events_before, me, done)

        info = {
            'winner': self._engine.winner if done else -1,
            'turn': self._engine.turn,
        }
        if done:
            info['z'] = _terminal_z(self._engine.winner)

        return obs, reward, done, info

    def _score_reward(self, events_before, me: int, done: bool) -> float:
        """Diff RewardEvents and apply the configured shaping. Returns
        0.0 when shaping is disabled (events_before is None in that
        case) — kept as a single call site so step() handles both the
        normal and need_target branches identically."""
        if self._reward_shaping is None or events_before is None:
            return 0.0
        events_after = self._engine.get_reward_events(me)
        return compute_shaped_reward(
            self._reward_shaping,
            events_before,
            events_after,
            done,
            self._engine.winner,
            me,
        )

    @property
    def obs_size(self):
        return self._dynamic_obs_size

    @property
    def static_obs_size(self):
        return self._static_obs_size

    @property
    def static_obs(self):
        return self._static_obs

    @property
    def current_player(self):
        """Alias for acting_player. The player currently owed a decision,
        which accounts for pending forced-switch states correctly."""
        return self._engine.acting_player

    @property
    def acting_player(self):
        """The player currently owed a decision. MCTS / search code
        should use this to determine node.turn, not raw engine.turn
        (which doesn't track forced-switch pending state)."""
        return self._engine.acting_player

    @property
    def has_pending(self):
        """True if a pending card target or forced switch is waiting."""
        return self._engine.has_pending

    @property
    def done(self):
        return self._engine.done

    @property
    def engine_handle(self):
        """Public access to the underlying c-shared engine handle for
        external cgo bindings(e.g. AZ MCTS go bindings call MCTSSearch
        directly on the engine handle)。 Pre W2-5 callers reached into
        ``env._engine._handle`` (audit finding 高优 — MCTS bindings 自
        ctypes 绕过 env);this property is the supported access path。"""
        return self._engine._handle

    @property
    def winner(self) -> int:
        """Engine winner code. -1 = game in progress, 0/1 = that player won,
        2 = draw. Callers querying terminal outcomes SHALL guard with
        ``env.done`` first; ``info['winner']`` returned from ``step()`` is
        the same value scoped to the step boundary."""
        return self._engine.winner

    @property
    def phase(self) -> int:
        """Engine phase enum (gicg_env._constants.PHASE_*). Matchup /
        selfplay loops use ``env.phase == PHASE_SELECT_ACTIVE`` to detect
        the initial active-char selection sub-phase before the regular
        action loop kicks in."""
        return self._engine.phase

    @property
    def current_round(self) -> int:
        """Current round number (1-based). Engine method name historically
        ``get_current_round()``; exposed as a property here so callers do
        not need to differentiate property vs method when reading raw
        engine state."""
        return self._engine.get_current_round()

    def hand_refs(self, player: int):
        """Hand card refs for ``player``. Forwards to the engine's pool
        query; exposed on env so callers do not need to reach into
        ``env._engine`` directly."""
        return self._engine.hand_refs(player)

    def dice_total(self, player: int) -> int:
        """Total dice count for ``player``. Forwards to the engine's pool
        query."""
        return self._engine.dice_total(player)

    def get_dynamic_obs(self, perspective: int | None = None):
        """Raw (un-normalized) dynamic obs from the Go side. ``_get_obs``
        already applies per-slot normalization for training paths;
        callers that need the raw int32 layout (AZ selfplay typed-segment
        decoding) use this method."""
        return self._engine.get_dynamic_obs(perspective=perspective)

    def random_rollout(self, seed: int, max_steps: int) -> tuple[int, int]:
        """Bypass-step random rollout to a terminal. Returns
        ``(winner, steps)``. Forwards to the engine's native rollout
        path used by AZ MCTS leaf evaluation."""
        return self._engine.random_rollout(seed=seed, max_steps=max_steps)

    @property
    def team_0(self):
        return list(self._team_0)

    @property
    def team_1(self):
        return list(self._team_1)

    @property
    def data_dir(self):
        return self._data_dir

    @property
    def card_pool(self):
        return None if self._card_pool is None else list(self._card_pool)

    def close(self):
        self._engine.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
