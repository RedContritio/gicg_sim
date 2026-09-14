"""Read-only query mixin for GicgEnv.

Thin pass-throughs over ``self._engine`` for legal-action enumeration,
action identities / refs / labels, replay + view export, and hook /
counter label introspection. Extracted from env.py to stay under the
300-line pre-commit cap; none of these methods mutate game state."""

from __future__ import annotations

import numpy as np


class _QueryMixin:
    def get_rule_graph(self):
        return self._engine.get_rule_graph()

    def get_legal_actions(self):
        return self._engine.get_legal_actions()

    def get_legal_action_payments(self):
        return self._engine.get_legal_action_payments()

    def get_action_identities(self):
        """See GicgEngine.get_action_identities — (n_legal, 5) int32."""
        return self._engine.get_action_identities()

    def get_legal_mask(self, max_actions):
        kinds, _ = self.get_legal_actions()
        mask = np.zeros(max_actions, dtype=bool)
        n = min(len(kinds), max_actions)
        mask[:n] = True
        return mask

    def active_char(self, player: int) -> int:
        """Returns the given player's currently active character slot
        (0..N-1), or -1 if unavailable. Used by hybrid opponent dispatch
        to decide which policy should play the opponent's current turn."""
        return int(self._engine._lib.GameGetActiveChar(self._engine._handle, int(player)))

    def export_view(self) -> dict:
        """Structured live-game-state snapshot for rendering. Thin
        wrapper over GicgEngine.export_view — see its docstring and
        gicg_engine/record/export_view.go :: StateView for the schema.
        Intended for the web UI (replay + live play) and any Python
        tool that needs human-readable state rather than obs tensors."""
        return self._engine.export_view()

    def replay_to(self, yaml_path: str, step: int) -> dict:
        """Rewind this env to the state after the first `step` actions
        of the YAML record at `yaml_path`. Env must have been built
        with teams matching the record (use record_extract_info to
        discover them). Returns the merged JSON dict; see
        GicgEngine.replay_to for the schema."""
        return self._engine.replay_to(yaml_path, step)

    def get_active_hook_labels(self):
        """Human-readable labels for the active hooks, in encode_static order."""
        return self._engine.get_active_hook_labels()

    def get_active_counter_slot_labels(self):
        """Labels for each observation counter slot; padding slots are ''."""
        return self._engine.get_active_counter_slot_labels()

    def get_action_labels(self):
        """List of (kind, name, slot) tuples aligned with
        get_legal_actions(). Resolved skill/card/char names from the
        engine registries. ``slot`` is hand_idx for Card, char_idx for
        Switch, -1 otherwise — disambiguates duplicate-name actions."""
        return self._engine.get_action_labels()

    def export_replay(self):
        """Engine-rendered replay YAML (same format as Go test fixtures)."""
        return self._engine.export_replay()

    def get_action_refs(self):
        """Thin passthrough to the engine; see engine.get_action_refs."""
        return self._engine.get_action_refs()

    def dice_counts(self, player: int) -> np.ndarray:
        """Return the player's LIVE per-color dice pool as a numpy int32
        array of length 8 (fire, ice, water, electro, geo, anemo,
        dendro, omni). Thin passthrough to the engine; used by
        GreedyPlayer's dice-value heuristic."""
        return self._engine.dice_counts(player)

    def reward_events(self, player: int) -> np.ndarray:
        """Read the RewardEvents accumulator for ``player`` as an int32
        array of length REWARD_EVENTS_COUNT (=14). Field order matches
        ``gicg_env._constants.REWARD_EVENTS_FIELDS``. Intended for
        opponents / evaluators that score states using raw occurrence
        signals (GreedyPlayer F3/F4/F5). Callers differencing pre- and
        post-step readings get per-action deltas without needing to
        reset the accumulator."""
        return self._engine.get_reward_events(player)
