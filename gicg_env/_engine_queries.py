"""Query methods for gicg_env.engine.GicgEngine — counters, static /
dynamic obs, phase / winner / turn / acting_player, label lists,
replay export, view JSON. All are read-only accessors; none mutate
the game handle. Hand / deck / discard / dice pool queries are
split out into engine_pool_queries.py to stay under the 300-line cap."""

from __future__ import annotations

import ctypes

import numpy as np

from gicg_env._constants import PHASE_GAME_OVER, REWARD_EVENTS_COUNT


class _QueriesMixin:
    """Provides read-only state / obs / label / replay accessors."""

    def get_rule_graph(self):
        """Public counter/rule/card links in this episode's shuffled layout."""
        import json

        self._check()
        ptr = self._lib.GameGetRuleGraphJSON(self._handle)
        if not ptr:
            raise RuntimeError('rule graph export failed')
        try:
            return json.loads(ctypes.string_at(ptr).decode('utf-8'))
        finally:
            self._lib.GameFreeString(ptr)

    def get_counters(self):
        """Returns shuffled counter values as numpy array."""
        self._check()
        n = self._lib.GameGetCounterCount(self._handle)
        values = (ctypes.c_int * n)()
        self._lib.GameGetCounters(self._handle, values, n)
        return np.array(values, dtype=np.int32)

    def get_reward_events(self, player: int) -> np.ndarray:
        """Return the per-player RewardEvents accumulator as an int32
        array of length REWARD_EVENTS_COUNT (=14). Field order matches
        ``gicg_env._constants.REWARD_EVENTS_FIELDS``. The engine only
        records occurrences — any scalar reward formula lives on top
        (GreedyPlayer F3/F4/F5, diagnostics, …).

        The returned array is a fresh copy; callers may snapshot a
        pre-action reading and subtract from a post-action reading
        without worrying about ctypes buffer lifetime."""
        self._check()
        buf = (ctypes.c_int * REWARD_EVENTS_COUNT)()
        self._lib.GameGetRewardEvents(self._handle, int(player), buf)
        return np.array(buf, dtype=np.int32)

    def reset_reward_events(self) -> None:
        """Zero the RewardEvents accumulator for both players. Intended
        for episode resets; per-step deltas should be computed by
        differencing before/after snapshots, not by mid-episode reset
        (cumulative fields like TotalKills would lose the escalation
        signal F5 reads)."""
        self._check()
        self._lib.GameResetReward(self._handle)

    def get_static_obs(self):
        """Returns static observation (hook tokens + counter metadata). Call once per episode."""
        self._check()
        n = self._lib.GameGetStaticObsSize()
        values = (ctypes.c_int * n)()
        self._lib.GameGetStaticObs(self._handle, values)
        return np.array(values, dtype=np.float32)

    def get_current_round(self):
        self._check()
        return int(self._lib.GameGetCurrentRound(self._handle))

    def get_card_names(self):
        """Return dict {ref: name} for every declared card. Used by env
        wrappers to translate human-readable card names to refs once at
        construction time."""
        self._check()
        ptr = self._lib.GameGetCardNames(self._handle)
        if not ptr:
            return {}
        try:
            s = ctypes.cast(ptr, ctypes.c_char_p).value
            if not s:
                return {}
            out = {}
            for line in s.decode('utf-8').split('\n'):
                if not line:
                    continue
                ref_s, _, name = line.partition('\t')
                out[int(ref_s)] = name
            return out
        finally:
            self._lib.GameFreeString(ptr)

    def get_active_hook_labels(self):
        """Returns a list of human-readable labels for the active hooks,
        in the same order encode_static filters them. Used by the
        checkpoint visualizer to annotate attention plots semantically."""
        return self._read_label_list(self._lib.GameGetActiveHookLabels)

    def get_active_counter_slot_labels(self):
        """Returns one label per observation counter slot (length
        N_COUNTER_SLOTS), matching BuildStaticObs's counter ordering.
        Padding slots get an empty string; active slots get labels like
        'P0:c0:赤蝶:生命' / 'P1:dice_fire' / 'global:round_num'."""
        return self._read_label_list(self._lib.GameGetActiveCounterSlotLabels)

    def get_action_labels(self):
        """Returns a list of (kind, name, slot) tuples for the *current*
        legal actions, in the same order as get_legal_actions(). Resolves
        skill IDs via SkillNames, hand indices via CardNames, switch
        indices via CharNames; unknown entries fall back to numeric
        labels. ``slot`` is:
          - ActionCard:   hand index (disambiguates duplicate-name cards)
          - ActionSwitch: target char slot
          - other:        -1
        """
        raw = self._read_label_list(self._lib.GameGetActionLabels)
        out = []
        for line in raw:
            parts = line.split('\t')
            kind = parts[0] if len(parts) > 0 else '?'
            name = parts[1] if len(parts) > 1 else '-'
            try:
                slot = int(parts[2]) if len(parts) > 2 else -1
            except ValueError:
                slot = -1
            out.append((kind, name, slot))
        return out

    def export_replay(self):
        """Returns the engine's textual replay record (the same Chinese
        YAML format used by Go integration tests under
        artifacts/<timestamp>_replays/go_tests/). Captures round-by-round
        state plus every action's effect chain. Read once after the game
        ends."""
        self._check()
        ptr = self._lib.GameExportReplay(self._handle)
        if not ptr:
            return ''
        try:
            s = ctypes.cast(ptr, ctypes.c_char_p).value
            return s.decode('utf-8') if s else ''
        finally:
            self._lib.GameFreeString(ptr)

    def replay_to(self, yaml_path: str, step: int) -> dict:
        """Rewind this engine's game to the state immediately after the
        first `step` actions of the YAML record at `yaml_path`. The
        engine's team roster and card pool must already match the
        record — construct a GicgEnv from record_extract_info(yaml_path)
        first. Returns the merged dict {view, step, total_steps,
        rounds, winner} decoded from the Go-side JSON wrapper; raises
        RuntimeError on any Go-reported error."""
        self._check()
        import json

        path_bytes = yaml_path.encode('utf-8')
        ptr = self._lib.GameReplayToJSON(self._handle, path_bytes, int(step))
        if not ptr:
            raise RuntimeError('GameReplayToJSON returned null')
        try:
            s = ctypes.cast(ptr, ctypes.c_char_p).value
            if not s:
                raise RuntimeError('GameReplayToJSON returned empty')
            data = json.loads(s.decode('utf-8'))
        finally:
            self._lib.GameFreeString(ptr)
        if 'error' in data:
            raise RuntimeError(f'replay_to {yaml_path}:{step}: {data["error"]}')
        return data

    def export_view(self) -> dict:
        """Returns the live game state as a structured dict (parsed
        from the Go engine's record.StateView JSON export). Call any
        time between steps — the dict reflects the current counters,
        hands, alive status, and phase. Intended for the web UI
        renderer (replay + live play) and diagnostic tooling that
        needs human-readable state rather than obs tensors.

        Schema: see gicg_engine/record/export_view.go :: StateView.
        Top-level keys: phase, round, turn, first_player, winner,
        players (array of 2, each with active_char, alive_count,
        chars, hand, deck_count)."""
        self._check()
        import json

        ptr = self._lib.GameExportViewJSON(self._handle)
        if not ptr:
            return {}
        try:
            s = ctypes.cast(ptr, ctypes.c_char_p).value
            if not s:
                return {}
            return json.loads(s.decode('utf-8'))
        finally:
            self._lib.GameFreeString(ptr)

    def _read_label_list(self, fn):
        """Shared helper for C-returned newline-joined label strings."""
        self._check()
        ptr = fn(self._handle)
        if not ptr:
            return []
        try:
            s = ctypes.cast(ptr, ctypes.c_char_p).value
            if not s:
                return []
            return s.decode('utf-8').split('\n')
        finally:
            self._lib.GameFreeString(ptr)

    def get_dynamic_obs(self, perspective=None):
        """Returns dynamic observation (counter values + hand cards). Call each step.

        Counter slots always use the static P0/P1 layout. Other public
        player-relative fields use ``perspective``, which defaults to
        ``acting_player`` (the decision-maker, including forced switches).
        Meta field 18 explicitly identifies this observer.
        """
        self._check()
        if perspective is None:
            perspective = self.acting_player
        n = self._lib.GameGetDynamicObsSize()
        values = (ctypes.c_int * n)()
        self._lib.GameGetDynamicObs(self._handle, perspective, values)
        return np.array(values, dtype=np.float32)

    @property
    def phase(self):
        self._check()
        return self._lib.GameGetPhase(self._handle)

    @property
    def winner(self):
        self._check()
        return self._lib.GameGetWinner(self._handle)

    @property
    def turn(self):
        self._check()
        return self._lib.GameGetTurn(self._handle)

    @property
    def acting_player(self):
        """The player currently owed a decision. Under normal play this
        equals turn, but switches to the victim player during a forced-
        switch pending state (after a char death). MCTS and step routing
        should use this instead of turn to correctly identify the
        decision-maker."""
        self._check()
        return self._lib.GameGetActingPlayer(self._handle)

    @property
    def has_pending(self):
        """True if the engine is in a pending state (pending card target
        or pending forced switch). Used to route the next step call to
        step_target instead of step."""
        self._check()
        return self._lib.GameHasPending(self._handle) != 0

    @property
    def done(self):
        return self.phase == PHASE_GAME_OVER
