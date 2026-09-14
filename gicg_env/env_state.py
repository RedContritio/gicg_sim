"""Public environment state properties and native query forwarding."""

from __future__ import annotations


class _StateMixin:
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
        external cgo bindings (for example, AZ MCTS calls MCTSSearch
        directly on the handle)."""
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
