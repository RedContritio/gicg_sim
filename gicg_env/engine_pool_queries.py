"""Hand / deck / discard / dice queries for GicgEngine. Split out of
_engine_queries.py to keep each file under the 300-line size cap.
These are the card-pool and dice-pool public accessors; IS-MCTS
determinization lives upstream of them."""

from __future__ import annotations

import ctypes


class _PoolQueriesMixin:
    """Card pool (hand / deck / discard) and dice pool accessors."""

    def hand_count(self, player):
        self._check()
        return self._lib.GameGetHandCount(self._handle, player)

    def deck_count(self, player):
        self._check()
        return self._lib.GameGetDeckCount(self._handle, player)

    def discard_count(self, player):
        self._check()
        return self._lib.GameGetDiscardCount(self._handle, player)

    def dice_total(self, player):
        """Total dice count in the given player's pool. Used by the
        IS-MCTS determinization sampler to know how many opponent
        dice to draw via multinomial."""
        self._check()
        return int(self._lib.GameGetDiceTotal(self._handle, player))

    def discard_refs(self, player):
        """Return the list of card_refs in a player's discard pile,
        in insertion order. Used by the IS-MCTS determinization
        sampler to subtract publicly-committed cards from a pool
        without routing through export_view (which also exposes the
        opponent's secret hand contents). Discard itself is public
        information, so this is safe to call for any player."""
        self._check()
        n = self._lib.GameGetDiscardCount(self._handle, player)
        if n == 0:
            return []
        buf = (ctypes.c_int * n)()
        self._lib.GameGetDiscardRefs(self._handle, player, buf)
        return [int(buf[i]) for i in range(n)]

    def hand_refs(self, player):
        """Return the list of card_refs in a player's hand. Hand contents
        are HIDDEN to the opposing player — callers should only query
        their OWN hand. IS-MCTS code must NEVER call this on the opponent
        (the whole point of determinization is to sample the opponent's
        hidden hand). Used by resolve_pool_refs to read the viewing
        player's own initial hand composition."""
        self._check()
        n = self._lib.GameGetHandCount(self._handle, player)
        if n == 0:
            return []
        buf = (ctypes.c_int * n)()
        self._lib.GameGetHandRefs(self._handle, player, buf)
        return [int(buf[i]) for i in range(n)]

    def deck_refs(self, player):
        """Return the list of card_refs in a player's deck, top-first.
        Deck contents are HIDDEN to the opposing player — IS-MCTS must
        never call this on the opponent. Used by resolve_pool_refs to
        read the viewing player's own initial deck composition at game
        start, to build an accurate SharedFixedPool multi-set."""
        self._check()
        n = self._lib.GameGetDeckCount(self._handle, player)
        if n == 0:
            return []
        buf = (ctypes.c_int * n)()
        self._lib.GameGetDeckRefs(self._handle, player, buf)
        return [int(buf[i]) for i in range(n)]

    def dice_counts(self, player):
        """Return the player's LIVE per-color dice pool as a numpy int32
        array of length 8 (one per DiceColor: fire, ice, water, electro,
        geo, anemo, dendro, omni). Unlike dice_paid (cumulative payment
        history) this reports the dice currently available to spend.
        Used by GreedyPlayer's dice-value heuristic to collapse the full
        payment fan-out to one top-1 payment per logical (kind, refs)
        action group."""
        self._check()
        import numpy as np

        from gicg_env._constants import DICE_COLOR_COUNT

        buf = (ctypes.c_int * DICE_COLOR_COUNT)()
        self._lib.GameGetDiceCounts(self._handle, player, buf)
        return np.array(buf, dtype=np.int32)

    def dice_paid(self, player):
        """Return the accumulated per-color dice payment counts for a
        player as a list of 8 ints (one per DiceColor: fire, ice, water,
        electro, geo, anemo, dendro, omni). These are publicly observable
        — in real MCG rules both players see every dice payment — and
        used by IS-MCTS sampling as Bayesian evidence: Dirichlet posterior
        over color shares given paid counts, then Multinomial sampling
        of the opponent's remaining dice."""
        self._check()
        from gicg_env._constants import DICE_COLOR_COUNT

        buf = (ctypes.c_int * DICE_COLOR_COUNT)()
        self._lib.GameGetDicePaid(self._handle, player, buf)
        return [int(buf[c]) for c in range(DICE_COLOR_COUNT)]

    def dice_tuned_out(self, player):
        """Return per-color dice counts consumed via tune's source_color
        (length 8). Complements dice_paid — tune's color consumption
        bypasses PayDice and lives in a separate accumulator. Additional
        Bayesian evidence for the opponent's dice posterior."""
        self._check()
        from gicg_env._constants import DICE_COLOR_COUNT

        buf = (ctypes.c_int * DICE_COLOR_COUNT)()
        self._lib.GameGetDiceTunedOut(self._handle, player, buf)
        return [int(buf[c]) for c in range(DICE_COLOR_COUNT)]

    def dice_tuned_in(self, player):
        """Return per-color dice counts gained via tune's target_color
        (length 8). Always the acting char's element color. Exposed for
        diagnostics; current posterior sampler ignores this (hard-floor
        modeling is a future refinement)."""
        self._check()
        from gicg_env._constants import DICE_COLOR_COUNT

        buf = (ctypes.c_int * DICE_COLOR_COUNT)()
        self._lib.GameGetDiceTunedIn(self._handle, player, buf)
        return [int(buf[c]) for c in range(DICE_COLOR_COUNT)]
