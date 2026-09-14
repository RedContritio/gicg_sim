package main

/*
#include <stdlib.h>
#include <string.h>
*/
import "C"

import (
	engine "gicg_mono/gicg_engine"
	"unsafe"
)

// State-accessor C exports: counters, phase, winner, turn, active char,
// hand/deck/dice totals, discard, static obs size + bytes.

//export GameGetCounters
func GameGetCounters(id C.int, outValues *C.int, count C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	n := int(count)
	if n > len(h.Game.Counters) {
		n = len(h.Game.Counters)
	}
	values := unsafe.Slice((*C.int)(unsafe.Pointer(outValues)), n)
	perm := h.Game.CounterPerm
	for i := 0; i < n; i++ {
		src := i
		if perm != nil && i < len(perm) {
			src = perm[i]
		}
		values[i] = C.int(h.Game.Counters[src].Value)
	}
}

//export GameGetPhase
func GameGetPhase(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	return C.int(h.Game.Phase)
}

//export GameGetWinner
func GameGetWinner(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	return C.int(h.Game.Winner)
}

//export GameGetTurn
func GameGetTurn(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	return C.int(h.Game.Turn)
}

// Returns the active character index (slot 0..N-1) for the given player,
// or -1 if unavailable. Used by hybrid opponent modes that dispatch
// different policies based on which of the opponent's chars is currently
// acting (e.g. slot 0 uses a prior checkpoint, other slots play random).
//
//export GameGetActiveChar
func GameGetActiveChar(id C.int, player C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	pi := int(player)
	if pi < 0 || pi >= len(h.Game.Players) {
		return -1
	}
	return C.int(h.Game.Players[pi].ActiveChar)
}

//export GameGetHandCount
func GameGetHandCount(id C.int, player C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	return C.int(len(h.Game.Players[int(player)].Hand))
}

//export GameGetDeckCount
func GameGetDeckCount(id C.int, player C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	return C.int(len(h.Game.Players[int(player)].Deck))
}

// GameGetDiceTotal returns the total number of dice currently in
// player pi's pool (sum over all 8 color counters). Used by the
// IS-MCTS determinization sampler to know how many opponent dice to
// sample via multinomial. Returns 0 if dice system isn't loaded.
//
//export GameGetDiceTotal
func GameGetDiceTotal(id C.int, player C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	pool := h.RT.DicePool(int(player))
	total := 0
	for _, v := range pool {
		total += v
	}
	return C.int(total)
}

// GameGetDiceCounts writes the current per-color dice count for a
// player into `out` (length 8). Unlike GameGetDicePaid (cumulative
// payment history) this is the LIVE pool — what the player could pay
// next action with. Used by GreedyPlayer's dice-value heuristic to
// collapse the full payment fan-out to one top-1 payment per logical
// action, and by any diagnostic tool that needs to introspect a
// player's current dice composition.
//
//export GameGetDiceCounts
func GameGetDiceCounts(id C.int, player C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	pool := h.RT.DicePool(int(player))
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), engine.DiceColorCount)
	for c := 0; c < engine.DiceColorCount; c++ {
		arr[c] = C.int(pool[c])
	}
}

//export GameGetDiscardCount
func GameGetDiscardCount(id C.int, player C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	return C.int(len(h.Game.Players[int(player)].Discard))
}

// GameGetDiscardRefs writes the card_ref of every entry in a player's
// discard pile into `out`, in insertion order. Caller must pre-size
// `out` to GameGetDiscardCount(id, player). Used by the MCTS
// determinization sampler to subtract publicly-committed cards from
// a pool without going through export_view (which also exposes the
// opponent's secret hand contents — a leak risk for IS-MCTS code).
//
//export GameGetDiscardRefs
func GameGetDiscardRefs(id C.int, player C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	discard := h.Game.Players[int(player)].Discard
	if len(discard) == 0 {
		return
	}
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), len(discard))
	for i, card := range discard {
		arr[i] = C.int(card.Ref)
	}
}

// GameGetHandRefs writes the card_ref of every card in a player's hand
// into `out`, in insertion order. Caller must pre-size `out` to
// GameGetHandCount(id, player). The viewing player is responsible for
// only calling this on their OWN hand — opponent's hand is hidden
// information; IS-MCTS sampling should never read it.
//
//export GameGetHandRefs
func GameGetHandRefs(id C.int, player C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	hand := h.Game.Players[int(player)].Hand
	if len(hand) == 0 {
		return
	}
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), len(hand))
	for i, card := range hand {
		arr[i] = C.int(card.Ref)
	}
}

// GameGetDeckRefs writes the card_ref of every card in a player's deck
// into `out`, in deck order (top = index 0). Caller must pre-size `out`
// to GameGetDeckCount(id, player). The viewing player should only call
// this on their OWN deck — deck contents are hidden information to the
// opposing player. Used by _resolve_pool_refs to read the actual deck
// composition at game start for SharedFixedPool construction.
//
//export GameGetDeckRefs
func GameGetDeckRefs(id C.int, player C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	deck := h.Game.Players[int(player)].Deck
	if len(deck) == 0 {
		return
	}
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), len(deck))
	for i, card := range deck {
		arr[i] = C.int(card.Ref)
	}
}

// GameGetDicePaid writes the accumulated per-color dice payment counts
// for a player into `out` (length 8). Incremented by engine.PayDice on
// every action payment. Public observation — IS-MCTS determinization
// uses this as Bayesian evidence: initial uniform Dirichlet prior +
// per-color paid counts → posterior over remaining dice color shares.
//
//export GameGetDicePaid
func GameGetDicePaid(id C.int, player C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	paid := h.Game.DicePaid[int(player)]
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), engine.DiceColorCount)
	for c := 0; c < engine.DiceColorCount; c++ {
		arr[c] = C.int(paid[c])
	}
}

// GameGetDiceTunedOut writes the accumulated per-color tune-source
// counts into `out` (length 8). Incremented in executeTune on the
// source_color side. Complements GameGetDicePaid as additional
// Bayesian evidence for IS-MCTS dice posterior — tune's color
// consumption bypasses PayDice so wasn't previously tracked.
//
//export GameGetDiceTunedOut
func GameGetDiceTunedOut(id C.int, player C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	tunedOut := h.Game.DiceTunedOut[int(player)]
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), engine.DiceColorCount)
	for c := 0; c < engine.DiceColorCount; c++ {
		arr[c] = C.int(tunedOut[c])
	}
}

// GameGetDiceTunedIn writes the accumulated per-color tune-target
// counts into `out` (length 8). Incremented in executeTune on the
// target_color side (always the active char's element color). Not
// used in current posterior sampling (hard-floor modeling deferred);
// exposed for diagnostics + future refinement.
//
//export GameGetDiceTunedIn
func GameGetDiceTunedIn(id C.int, player C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	tunedIn := h.Game.DiceTunedIn[int(player)]
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), engine.DiceColorCount)
	for c := 0; c < engine.DiceColorCount; c++ {
		arr[c] = C.int(tunedIn[c])
	}
}
