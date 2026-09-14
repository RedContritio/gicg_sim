package main

/*
#include <stdlib.h>
#include <string.h>
*/
import "C"

import (
	engine "gicg_mono/gicg_engine"
	"math/rand"
	"unsafe"
)

// Action execution + state-setter C exports (Step, StepTarget, Reset,
// SetPlayerHand/Deck/Dice, RandomRollout). Legal-action queries +
// identities / refs / payments live in capi_actions_query.go.

//export GameGetActingPlayer
func GameGetActingPlayer(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	return C.int(h.Game.ActingPlayer())
}

// GameHasPending reports whether the engine is in a pending state
// (pending card target or pending forced switch). Python env.step
// uses this to route to step vs step_target without needing a local
// Python-side flag that would break under snapshot / restore.
// Returns 1 if pending, 0 otherwise.
//
//export GameHasPending
func GameHasPending(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	if h.Game.HasPending() {
		return 1
	}
	return 0
}

//export GameSetPlayerHand
func GameSetPlayerHand(id C.int, player C.int, refs *C.int, n C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	count := int(n)
	goRefs := make([]int, count)
	if count > 0 {
		cSlice := unsafe.Slice((*C.int)(unsafe.Pointer(refs)), count)
		for i := 0; i < count; i++ {
			goRefs[i] = int(cSlice[i])
		}
	}
	h.Game.SetPlayerHand(int(player), goRefs)
	return 0
}

// GameSetPlayerDeck overwrites a player's deck with the given refs.
// refs[0] is the top of the deck (next to be drawn). Used by IS-MCTS
// determinization. Returns 0 on success, -1 on invalid handle.
//
//export GameSetPlayerDeck
func GameSetPlayerDeck(id C.int, player C.int, refs *C.int, n C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	count := int(n)
	goRefs := make([]int, count)
	if count > 0 {
		cSlice := unsafe.Slice((*C.int)(unsafe.Pointer(refs)), count)
		for i := 0; i < count; i++ {
			goRefs[i] = int(cSlice[i])
		}
	}
	h.Game.SetPlayerDeck(int(player), goRefs)
	return 0
}

// GameSetPlayerDice overwrites a player's dice pool with 8 per-color
// counts (indexed by DiceColor: fire=0, ice=1, water=2, electro=3,
// geo=4, anemo=5, dendro=6, omni=7). counts must point to exactly 8
// ints. Used by IS-MCTS determinization to inject a sampled opponent
// dice distribution. Returns 0 on success, -1 on invalid handle.
//
//export GameSetPlayerDice
func GameSetPlayerDice(id C.int, player C.int, counts *C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	var goCounts [engine.DiceColorCount]int
	cSlice := unsafe.Slice((*C.int)(unsafe.Pointer(counts)), engine.DiceColorCount)
	for i := 0; i < engine.DiceColorCount; i++ {
		goCounts[i] = int(cSlice[i])
	}
	h.RT.SetPlayerDice(int(player), goCounts)
	return 0
}

//export GameReset
func GameReset(id C.int, seed C.long) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	h.RT.ResetDynamic(int64(seed))
}

// GameResetSeeds performs a three-axis seed reset. diceSeed
// controls dice rolls + DSL random_non_active + obs InitShuffle. deckSeed0
// / deckSeed1 control per-player deck Fisher-Yates shuffle independently.
//
//export GameResetSeeds
func GameResetSeeds(id C.int, diceSeed C.long, deckSeed0 C.long, deckSeed1 C.long) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	h.RT.ResetDynamicWithSeeds(int64(diceSeed), [2]int64{int64(deckSeed0), int64(deckSeed1)})
}

//export GameStep
func GameStep(id C.int, actionIdx C.int) (ret C.int) {
	defer recoverRuleErrorInt(id, &ret)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	h.RT.CurrentContextPlayer = h.Game.Turn
	result := h.Game.Step(int(actionIdx))
	return C.int(result)
}

//export GameStepTarget
func GameStepTarget(id C.int, targetIdx C.int) (ret C.int) {
	defer recoverRuleErrorInt(id, &ret)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	result := h.Game.StepTarget(int(targetIdx))
	return C.int(result)
}

// GameRandomRollout plays uniformly-random actions from the current
// state until terminal or maxSteps. Returns Game.Winner (-1 live,
// 0/1 player win, 2 draw) and writes n_steps via nStepsOut.
//
// It runs entirely in Go to avoid repeated ctypes round-trips.
//
// Handles pending state (card target, forced switch) the same way
// Python env.step does: dispatch on HasPending(), call StepTarget
// or Step as appropriate. GetLegalActions() returns the right list
// in either case.
//
// The RNG is seeded from seed, so the same seed and starting state
// produce the same trajectory.
//
// Caller retains responsibility for snapshot/restore — this function
// mutates the game state to terminal (or maxSteps).
//
//export GameRandomRollout
func GameRandomRollout(id C.int, seed C.ulonglong, maxSteps C.int, nStepsOut *C.int) (ret C.int) {
	defer recoverRuleErrorInt(id, &ret)
	h := getHandle(int(id))
	if h == nil {
		return -99
	}
	rng := rand.New(rand.NewSource(int64(seed)))
	steps := 0
	for i := 0; i < int(maxSteps); i++ {
		if h.Game.Phase == engine.PhaseGameOver {
			break
		}
		h.RT.CurrentContextPlayer = h.Game.Turn
		actions := h.Game.GetLegalActions()
		n := len(actions)
		if n == 0 {
			break
		}
		idx := rng.Intn(n)
		if h.Game.HasPending() {
			h.Game.StepTarget(idx)
		} else {
			h.Game.Step(idx)
		}
		steps++
	}
	if nStepsOut != nil {
		*nStepsOut = C.int(steps)
	}
	if h.Game.Phase == engine.PhaseGameOver {
		return C.int(h.Game.Winner)
	}
	return -1
}
