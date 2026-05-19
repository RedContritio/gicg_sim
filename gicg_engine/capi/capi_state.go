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
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	return C.int(h.Game.Phase)
}

//export GameGetWinner
func GameGetWinner(id C.int) C.int {
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	return C.int(h.Game.Winner)
}

//export GameGetTurn
func GameGetTurn(id C.int) C.int {
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
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	return C.int(len(h.Game.Players[int(player)].Hand))
}

//export GameGetDeckCount
func GameGetDeckCount(id C.int, player C.int) C.int {
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

//export GameGetStaticObsSize
func GameGetStaticObsSize() C.int {
	return C.int(engine.StaticObsSize())
}

//export GameGetDynamicObsSize
func GameGetDynamicObsSize() C.int {
	return C.int(engine.DynamicObsSize())
}

// GameGetReactionCount — Round-6 S-1: Python verify ReactionCount ≤
// REACTION_VOCAB-3 at game init (push reaction-count check 从 forward
// raise 到 game init,DSL declare 越界即时报错)。
//
//export GameGetReactionCount
func GameGetReactionCount(id C.int) C.int {
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	return C.int(h.Game.ReactionCount())
}

// GameGetTypedObsConstants exports the 8 Go-side obs layout constants
// Python uses to compute typed-segment offsets, so Python can verify
// its hard-coded mirrors match at startup (review B2 + Round-2 M2 —
// hand block constants also affect typed segment slicing offset; if
// those drift Go↔Python the typed segments read from wrong positions
// without _verify catching it).
//
// Output array layout (8 * sizeof(int)):
//
//	[0] OBS_RECENT_DAMAGE_EVENTS
//	[1] OBS_RECENT_DAMAGE_FIELD_COUNT
//	[2] OBS_PREPARE_SKILL_SLOTS
//	[3] OBS_MODIFIER_LOG_K_MOD
//	[4] OBS_MODIFIER_LOG_FIELD_COUNT
//	[5] OBS_MAX_CARD_TYPES        — hand bucket width (Round-2 M2)
//	[6] OBS_HAND_BUCKETS          — number of hand buckets (Round-2 M2)
//	[7] OBS_ENEMY_SIZES_HARDCODED — hand-block trailing scalar count (Round-2 M2)
//
//export GameGetTypedObsConstants
func GameGetTypedObsConstants(out *C.int) {
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), 8)
	arr[0] = C.int(engine.ObsRecentDamageEvents)
	arr[1] = C.int(engine.ObsRecentDamageFieldCount)
	arr[2] = C.int(engine.ObsPrepareSkillSlots)
	arr[3] = C.int(engine.ObsModifierLogKMod)
	arr[4] = C.int(engine.ObsModifierLogFieldCount)
	arr[5] = C.int(engine.ObsMaxCardTypes)
	arr[6] = 4 // OBS_HAND_BUCKETS — hardcoded in observation_dynamic.go (own hand/deck/discard + enemy discard)
	arr[7] = 2 // OBS_ENEMY_SIZES — enemy hand/deck size scalars
}

// GameGetIRLayoutConstants exports the IR-2.b.2 hook obs layout
// constants (replaces the legacy ObsMaxTokensPerHook × 2 token-pair
// segment). Python uses these to slice the hook section of static obs
// into (n_hooks, max_ops, fields) for the IR encoder.
//
// Output array layout (4 * sizeof(int)):
//
//	[0] OBS_MAX_HOOKS               — hook slot count
//	[1] OBS_MAX_OPS_PER_HOOK        — max IR ops per hook
//	[2] OBS_FIELDS_PER_OP           — int32 fields per op (= 5)
//	[3] OBS_INTS_PER_HOOK           — slot size = OPS × FIELDS
//
//export GameGetIRLayoutConstants
func GameGetIRLayoutConstants(out *C.int) {
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), 4)
	arr[0] = C.int(engine.ObsMaxHooks)
	arr[1] = C.int(engine.ObsMaxOpsPerHook)
	arr[2] = C.int(engine.ObsFieldsPerOp)
	arr[3] = C.int(engine.ObsIntsPerHook)
}

//export GameGetStaticObs
func GameGetStaticObs(id C.int, out *C.int) {
	h := getHandle(int(id))
	if h == nil {
		return
	}
	obs := h.Game.BuildStaticObs()
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), len(obs))
	for i, v := range obs {
		arr[i] = C.int(v)
	}
}
