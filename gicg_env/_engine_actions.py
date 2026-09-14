"""Action-loop methods for gicg_env.engine.GicgEngine — step,
step_target, random_rollout, legal action enumeration, action refs /
identities, forced-switch detection. These mirror 1:1 the C
exports named GameStep* / GameGetLegalAction* / GameGetActionRefs /
GameGetActionIdentities / GameIsForcedSwitchPending in
gicg_engine/capi/capi_actions.go."""

from __future__ import annotations

import ctypes

import numpy as np

from gicg_env._constants import DICE_COLOR_COUNT


class _ActionsMixin:
    """Provides step(), step_target(), random_rollout(), and all
    legal-action accessors."""

    def step(self, action_idx):
        """Execute an action by index in the legal actions list.

        After the step, force auto-advance past any inter-round pause
        (PHASE_ROUND_START) so Python callers never observe the internal
        pause state — they see PHASE_ACTION / PHASE_GAME_OVER directly.
        """
        self._check()
        result = self._lib.GameStep(self._handle, action_idx)
        # Probing legal-action count triggers Go's auto-advance from
        # PhaseRoundStart into PhaseAction via the next round's hooks.
        self._lib.GameGetLegalActionCount(self._handle)
        return result

    def step_target(self, target_idx):
        """Select a target (for cards that need target selection)."""
        self._check()
        result = self._lib.GameStepTarget(self._handle, target_idx)
        self._lib.GameGetLegalActionCount(self._handle)
        return result

    def random_rollout(self, seed: int, max_steps: int) -> tuple[int, int]:
        """Play uniformly-random actions from current state until
        terminal or max_steps.

        Returns ``(winner, n_steps)``:
          winner: -1 if not terminal, else engine's Winner code
                  (0 = P0 wins, 1 = P1 wins, 2 = draw)
          n_steps: number of step/step_target calls made

        Equivalent to training/mcts.py::_random_rollout_value but runs
        entirely in Go, saving ~30 ctypes round-trips per rollout. At
        team_size=2 (80 steps × 2 calls) this is the dominant MCTS cost.

        Seed → deterministic rollout given same starting state.

        Mutates engine state (stepped to terminal or maxSteps). Caller
        is responsible for snapshot/restore around this call.
        """
        self._check()
        n_steps = ctypes.c_int(0)
        winner = self._lib.GameRandomRollout(
            self._handle,
            ctypes.c_ulonglong(seed & 0xFFFFFFFFFFFFFFFF),
            max_steps,
            ctypes.byref(n_steps),
        )
        return int(winner), int(n_steps.value)

    def get_legal_actions(self):
        """Returns (kinds, indices) numpy arrays of legal actions."""
        self._check()
        n = self._lib.GameGetLegalActionCount(self._handle)
        if n == 0:
            return np.array([], dtype=np.int32), np.array([], dtype=np.int32)
        kinds = (ctypes.c_int * n)()
        indices = (ctypes.c_int * n)()
        self._lib.GameGetLegalActions(self._handle, kinds, indices)
        return (
            np.array(kinds, dtype=np.int32),
            np.array(indices, dtype=np.int32),
        )

    def get_legal_action_payments(self):
        """Returns an (n_legal, 8) int32 array of per-action dice
        payments. Columns index by DiceColor (fire, ice, water,
        electro, geo, anemo, dendro, omni). Rows align with
        get_legal_actions() ordering.

        Actions that pay no dice (end-turn, tune, free-action
        discounts at zero cost) return an all-zero row. The total of
        a row is the actual dice count the engine will debit via
        PayDice when the action executes."""
        self._check()
        n = self._lib.GameGetLegalActionCount(self._handle)
        if n == 0:
            return np.zeros((0, DICE_COLOR_COUNT), dtype=np.int32)
        buf = (ctypes.c_int * (DICE_COLOR_COUNT * n))()
        self._lib.GameGetLegalActionPayments(self._handle, buf)
        return np.array(buf, dtype=np.int32).reshape(n, DICE_COLOR_COUNT)

    def get_action_refs(self):
        """Returns a (n_legal, 3) int32 array of [kind, hook_idx, char_idx]
        for each current legal action, used by the pointer-net policy head
        to fetch a semantic embedding per action.
          - ActionSkill: hook_idx = active-hook index of the canonical
            on_skill_use hook for (actor_player, actor_char, skill_id).
          - ActionCard:  hook_idx = active-hook index of the canonical
            on_card_play hook for the card_ref; char_idx = target slot,
            own 0..5 / enemy 6..11, or -1 when untargeted.
          - ActionSwitch: char_idx = target char slot (NOT shuffled).
          - ActionEndTurn: both -1 (head uses a learned constant).
          - ActionTune: hook_idx identifies the discarded card rule;
            char_idx is the converted die's source color (0..7).
          - ActionReroll: field 1 is the selected count, NOT a hook;
            field 2 is color 0..7, or 8 for confirmation (count 0).
        hook_idx / char_idx unused by a given kind are -1.
        """
        self._check()
        n = self._lib.GameGetLegalActionCount(self._handle)
        if n == 0:
            return np.zeros((0, 3), dtype=np.int32)
        buf = (ctypes.c_int * (3 * n))()
        self._lib.GameGetActionRefs(self._handle, buf)
        return np.array(buf, dtype=np.int32).reshape(n, 3)

    def get_action_identities(self):
        """Returns an (n_legal, 5) int32 array of engine-native action
        identities for MCTS children-dict keying. The 5 columns are
        [kind, subject_ref, aux, target_player, target_char] with
        semantics documented on the Go export ``GameGetActionIdentities``.

        Unlike get_action_refs (which returns permutation-dependent
        hook indices for the pointer-net), these values are stable
        across determinizations and game resets — two rollouts
        observing the same logical action (e.g. "play 铁剑") will get
        the same identity row.

        Compose with get_legal_action_payments() to form a fully
        disambiguated MCTS identity: (kind, subject_ref, aux,
        target_player, target_char, tuple(payment_8d)).
        """
        self._check()
        n = self._lib.GameGetLegalActionCount(self._handle)
        if n == 0:
            return np.zeros((0, 5), dtype=np.int32)
        buf = (ctypes.c_int * (5 * n))()
        self._lib.GameGetActionIdentities(self._handle, buf)
        return np.array(buf, dtype=np.int32).reshape(n, 5)

    def is_forced_switch_pending(self):
        """True when the engine is waiting for a forced switch (death,
        overload). Python-side reward shaping uses this to classify an
        incoming Switch action as voluntary vs forced."""
        self._check()
        return bool(self._lib.GameIsForcedSwitchPending(self._handle))
