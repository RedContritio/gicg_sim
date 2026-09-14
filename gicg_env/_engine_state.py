"""Engine resets, snapshots, logging suspension and hidden-state setters."""

from __future__ import annotations

import ctypes

from gicg_env._constants import DICE_COLOR_COUNT


class _EngineStateMixin:
    def reset_dynamic(self, seed):
        """Restart the dynamic state of the current game without re-loading
        DSL files. The team and card pool are preserved."""
        self._check(allow_failed=True)
        self._lib.GameReset(self._handle, seed)

    def reset_dynamic_with_seeds(self, dice_seed, deck_seed_p0, deck_seed_p1):
        """Reset with independent dice/DSL and per-player deck seeds.

        ``dice_seed`` controls dice rolls, DSL randomness, and observation
        permutation. ``deck_seed_p0`` and ``deck_seed_p1`` independently
        seed each player's Fisher-Yates deck shuffle.
        """
        self._check(allow_failed=True)
        self._lib.GameResetSeeds(self._handle, dice_seed, deck_seed_p0, deck_seed_p1)

    def clone(self):
        """Return a new GicgEngine wrapping a clone of this game.

        The clone shares the static Ruleset (DSL definitions) but owns its
        own dynamic state — stepping the clone does not affect this engine.
        """
        self._check()
        new_handle = self._lib.GameClone(self._handle)
        if new_handle < 0:
            raise RuntimeError('Failed to clone game')
        from gicg_env.engine import GicgEngine

        twin = GicgEngine.__new__(GicgEngine)
        twin._lib = self._lib
        twin._handle = new_handle
        return twin

    def snapshot(self):
        """Capture the current dynamic state into a cheap handle. Use
        restore(snap_id) to roll back, snapshot_free(snap_id) to release.
        Snapshots are valid only at quiescent points (between Step calls).
        """
        self._check()
        sid = self._lib.GameSnapshot(self._handle)
        if sid < 0:
            raise RuntimeError('Failed to snapshot game')
        return sid

    def restore(self, snap_id):
        """Restore dynamic state from a snapshot taken via snapshot()."""
        self._check()
        if self._lib.GameRestore(self._handle, snap_id) < 0:
            raise RuntimeError(f'Failed to restore snapshot {snap_id}')

    def snapshot_free(self, snap_id):
        """Release a snapshot handle."""
        self._lib.GameSnapshotFree(snap_id)

    def set_simulation_seed(self, seed: int):
        """Replace future chance events for a speculative branch after restore.

        Does not change current hands/dice. Restore the original snapshot before
        resuming live play. The signed 64-bit range is validated before ctypes.
        """
        self._check()
        if not -(1 << 63) <= seed < (1 << 63):
            raise ValueError('simulation seed must fit signed int64')
        if self._lib.GameSetSimulationSeed(self._handle, seed) < 0:
            raise RuntimeError('Failed to set simulation seed')

    def log_suspend(self):
        """Detach the event log so subsequent engine events aren't
        recorded. Use around MCTS rollouts (or any speculative forward
        simulation): the inner events don't belong in the replay, and
        skipping the Log.Append + string-formatting overhead per step
        is a meaningful speedup. Idempotent: calling while already
        suspended raises."""
        self._check()
        rc = self._lib.GameLogSuspend(self._handle)
        if rc < 0:
            raise RuntimeError(f'GameLogSuspend failed (rc={rc}); is the log already suspended?')

    def log_resume(self):
        """Re-attach the event log suspended by ``log_suspend``.
        Events written while suspended are permanently lost — that's
        the point of this API. Raises if no log was suspended."""
        self._check()
        rc = self._lib.GameLogResume(self._handle)
        if rc < 0:
            raise RuntimeError(f'GameLogResume failed (rc={rc}); was log_suspend() called first?')

    def set_player_hand(self, player, refs):
        """Overwrite a player's hand with the given card refs. Each ref
        becomes a new CardInst with DrawnAtRound stamped to the current
        round.

        Intended for IS-MCTS determinization: the sampler generates a
        hypothetical opponent hand and injects it into a cloned engine
        before rolling forward. Caller is responsible for ref validity.

        Args:
            player: 0 or 1
            refs: list/sequence of int card refs. Empty list clears hand.
        """
        self._check()
        if player not in (0, 1):
            raise ValueError(f'set_player_hand: player must be 0 or 1, got {player}')
        n = len(refs)
        arr = (ctypes.c_int * n)(*refs) if n > 0 else (ctypes.c_int * 0)()
        rc = self._lib.GameSetPlayerHand(self._handle, int(player), arr, n)
        if rc < 0:
            raise RuntimeError(f'GameSetPlayerHand failed for player {player}')

    def set_player_deck(self, player, refs):
        """Overwrite a player's deck with the given card refs. ``refs[0]``
        is the top of the deck (next to be drawn). Each ref becomes a
        new CardInst with DrawnAtRound=0.

        Intended for IS-MCTS determinization.

        Args:
            player: 0 or 1
            refs: list/sequence of int card refs. Empty list clears deck.
        """
        self._check()
        if player not in (0, 1):
            raise ValueError(f'set_player_deck: player must be 0 or 1, got {player}')
        n = len(refs)
        arr = (ctypes.c_int * n)(*refs) if n > 0 else (ctypes.c_int * 0)()
        rc = self._lib.GameSetPlayerDeck(self._handle, int(player), arr, n)
        if rc < 0:
            raise RuntimeError(f'GameSetPlayerDeck failed for player {player}')

    def set_player_dice(self, player, counts):
        """Overwrite a player's dice pool with exact per-color counts.

        ``counts`` must be an 8-element sequence indexed by dice color
        (fire=0, ice=1, water=2, electro=3, geo=4, anemo=5, dendro=6,
        omni=7). Negative values are rejected before calling Go. Intended
        for IS-MCTS determinization: the sampler draws a
        multinomial dice distribution for the opponent and injects it
        into the cloned engine before rolling forward.

        Args:
            player: 0 or 1
            counts: sequence of 8 ints. Longer/shorter inputs raise.
        """
        self._check()
        if player not in (0, 1):
            raise ValueError(f'set_player_dice: player must be 0 or 1, got {player}')
        if len(counts) != DICE_COLOR_COUNT:
            raise ValueError(f'set_player_dice expects {DICE_COLOR_COUNT} counts, got {len(counts)}')
        ints = [int(x) for x in counts]
        for i, v in enumerate(ints):
            if v < 0:
                raise ValueError(f'set_player_dice: counts[{i}]={v} is negative')
        arr = (ctypes.c_int * DICE_COLOR_COUNT)(*ints)
        rc = self._lib.GameSetPlayerDice(self._handle, int(player), arr)
        if rc < 0:
            raise RuntimeError(f'GameSetPlayerDice failed for player {player}')
