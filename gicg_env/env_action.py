"""Action-routing + hidden-state-injection mixin for GicgEnv.

Thin wrappers over ``self._engine`` covering:

  * snapshot / restore / snapshot_free — state handles for MCTS rollouts
  * log_suspend / log_resume — silence replay log during MCTS forward sim
  * set_player_dice / set_player_hand / set_player_deck — IS-MCTS
    determinization injection points

Grouping them here keeps env.py under the 300-line pre-commit cap while
preserving the flat public API on GicgEnv (mixins inherit on the class,
so callers still write ``env.snapshot()`` etc.)."""

from __future__ import annotations


class _ActionMixin:
    def snapshot(self):
        """Capture current state into a cheap handle for later restore()."""
        return self._engine.snapshot()

    def restore(self, snap_id):
        """Restore from a snapshot taken via snapshot()."""
        self._engine.restore(snap_id)

    def snapshot_free(self, snap_id):
        """Release a snapshot handle."""
        self._engine.snapshot_free(snap_id)

    def set_simulation_seed(self, seed: int):
        """Set future chance events for a speculative branch after snapshot."""
        self._engine.set_simulation_seed(seed)

    def log_suspend(self):
        """Stop recording engine events into the replay log. Use around
        MCTS forward-simulation so rollout events don't end up in the
        replay + skip the per-event append/format overhead."""
        self._engine.log_suspend()

    def log_resume(self):
        """Resume event logging after ``log_suspend``. Events written
        while suspended are gone."""
        self._engine.log_resume()

    def set_player_dice(self, player, counts):
        """Overwrite a player's dice pool with exact per-color counts.
        See GicgEngine.set_player_dice for the counts layout."""
        self._engine.set_player_dice(player, counts)

    def set_player_hand(self, player, refs):
        """Overwrite a player's hand with the given card refs. Used by
        IS-MCTS determinization to inject hypothetical opponent state."""
        self._engine.set_player_hand(player, refs)

    def set_player_deck(self, player, refs):
        """Overwrite a player's deck with the given card refs in order.
        refs[0] is the top of deck (next to draw)."""
        self._engine.set_player_deck(player, refs)
