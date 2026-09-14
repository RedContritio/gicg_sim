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

// Action query C exports: identities, refs, legal actions, payments,
// and counts. Step / setters / rollout live in capi_actions.go.

//export GameGetLegalActionCount
func GameGetLegalActionCount(id C.int) (ret C.int) {
	defer recoverRuleErrorInt(id, &ret)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	return C.int(len(h.Game.GetLegalActions()))
}

// Writes 5 ints per legal action: [kind, subject_ref, aux,
// target_player, target_char]. Used by IS-MCTS to build a
// determinization-stable identity key for each action. Unlike
// GameGetActionRefs which emits position-in-obs indices that the
// pointer-net policy consumes, these are engine-native, permutation-
// independent identifiers.
//
// Semantics per kind (all integers; -1 means "not applicable"):
//
//	Skill:   subject_ref = skill_id (global, stable)
//	         aux = -1
//	         target_player/char = -1/-1 (skills self-target at
//	           execute time based on active char; no fan-out here)
//	Card:    subject_ref = card_ref
//	         aux = -1
//	         target_player/char = HasTarget ? (TargetPlayer, TargetChar) : (-1, -1)
//	Switch:  subject_ref = target_char_slot (= a.Index)
//	         aux = -1
//	         target_player/char = -1/-1
//	Tune:    subject_ref = card_ref read from Players[pi].Hand[a.Index].Ref
//	         aux = TuneSourceColor
//	         target_player/char = -1/-1
//	EndTurn: all fields = -1 (kind tells them apart)
//
// Together with GameGetLegalActionPayments, these compose the full
// MCTS identity tuple: (kind, subject_ref, aux, target_player,
// target_char, payment_8d). Caller must pre-size `out` to
// 5 * GameGetLegalActionCount().
//
//export GameGetActionIdentities
func GameGetActionIdentities(id C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	g := h.Game
	actions := g.GetLegalActions()
	if len(actions) == 0 {
		return
	}
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), 5*len(actions))
	for i, a := range actions {
		kind := int(a.Kind)
		subject := -1
		aux := -1
		tgtP := -1
		tgtC := -1
		switch a.Kind {
		case engine.ActionReroll:
			subject, aux = a.Index, a.RerollColor
		case engine.ActionSkill:
			subject = a.Index // globally-unique skill ID
		case engine.ActionCard:
			pi := a.PlayerIdx
			if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
				subject = g.Players[pi].Hand[a.Index].Ref
			}
			if a.HasTarget {
				tgtP = a.TargetPlayer
				tgtC = a.TargetChar
			}
			if a.HasBuffTarget {
				aux, tgtP, tgtC = a.TargetBuff, a.TargetPlayer, -1
			}
			if a.HasSupportTarget {
				aux, tgtP, tgtC = engine.ObsBuffRows+a.TargetSupport, a.PlayerIdx, -1
			}
		case engine.ActionSwitch:
			subject = a.Index // target char slot
		case engine.ActionTune:
			pi := a.PlayerIdx
			if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
				subject = g.Players[pi].Hand[a.Index].Ref
			}
			aux = a.TuneSourceColor
		}
		arr[5*i] = C.int(kind)
		arr[5*i+1] = C.int(subject)
		arr[5*i+2] = C.int(aux)
		arr[5*i+3] = C.int(tgtP)
		arr[5*i+4] = C.int(tgtC)
	}
}

// Writes 3 ints per legal action into `out`: [kind, hook_idx, char_idx].
// Used by the pointer-net policy head to look up a semantic embedding for
// each action:
//   - ActionSkill: hook_idx = canonical on_skill_use hook's active-index
//     for (actor_player, actor_char, skill_id); char_idx = -1.
//   - ActionCard:  hook_idx = canonical on_card_play hook's active-index
//     for the card_ref; char_idx = ActionCharRef (own-first card target).
//   - ActionSwitch: hook_idx = -1; char_idx = target char slot (NOT shuffled).
//   - ActionEndTurn: hook_idx = -1; char_idx = -1.
//   - ActionTune: hook_idx = discarded card hook; char_idx = source die color.
//   - ActionReroll: hook_idx stores the selected count; char_idx stores the
//     color, or 8 for confirmation.
//
// Caller must pre-size `out` to 3 * GameGetLegalActionCount().
//
//export GameGetActionRefs
func GameGetActionRefs(id C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	g := h.Game
	actions := g.GetLegalActions()
	if len(actions) == 0 {
		return
	}
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), 3*len(actions))
	rawToActive := g.BuildRawToActiveHookIdx()
	for i, a := range actions {
		kind := int(a.Kind)
		hookIdx := -1
		charIdx := engine.ActionCharRef(a)
		switch a.Kind {
		case engine.ActionReroll:
			hookIdx = a.Index // quantity, not a hook for this action kind
		case engine.ActionSkill:
			pi := a.PlayerIdx
			ci := g.Players[pi].ActiveChar
			if rawID, ok := g.CanonicalSkillHooks[[3]int{pi, ci, a.Index}]; ok {
				if ai, ok2 := rawToActive[rawID]; ok2 {
					hookIdx = ai
				}
			}
		case engine.ActionCard, engine.ActionTune:
			pi := a.PlayerIdx
			ref := -1
			if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
				ref = g.Players[pi].Hand[a.Index].Ref
			}
			if ref >= 0 {
				if rawID, ok := g.CanonicalCardHooks[ref]; ok {
					if ai, ok2 := rawToActive[rawID]; ok2 {
						hookIdx = ai
					}
				}
			}
		case engine.ActionSwitch:
			charIdx = a.Index
		}
		arr[3*i] = C.int(kind)
		arr[3*i+1] = C.int(hookIdx)
		arr[3*i+2] = C.int(charIdx)
	}
}

//export GameGetLegalActions
func GameGetLegalActions(id C.int, outKinds *C.int, outIndices *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	actions := h.Game.GetLegalActions()
	kinds := unsafe.Slice((*C.int)(unsafe.Pointer(outKinds)), len(actions))
	indices := unsafe.Slice((*C.int)(unsafe.Pointer(outIndices)), len(actions))
	for i, a := range actions {
		kinds[i] = C.int(a.Kind)
		indices[i] = C.int(a.Index)
	}
}

// Writes per-action DicePayment arrays into `out`. The layout is
// row-major: out[action_i * DiceColorCount + color] = payment count
// for that color. Caller must pre-size `out` to
// DiceColorCount * GameGetLegalActionCount().
//
// DiceColorCount is 8 (fire, ice, water, electro, geo, anemo, dendro,
// omni). For end-turn / tune actions (no dice cost), all 8 slots are
// zero. This lets callers inspect per-action dice spend without
// reconstructing it from the observation.
//
//export GameGetLegalActionPayments
func GameGetLegalActionPayments(id C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	actions := h.Game.GetLegalActions()
	if len(actions) == 0 {
		return
	}
	nColors := engine.DiceColorCount
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), nColors*len(actions))
	for i, a := range actions {
		base := i * nColors
		for c := 0; c < nColors; c++ {
			arr[base+c] = C.int(a.DicePayment[c])
		}
	}
}

// Returns the constant DiceColorCount (currently 8). Python uses
// this to size the payment buffer without hardcoding the number.
//
//export GameGetDiceColorCount
func GameGetDiceColorCount() C.int {
	return C.int(engine.DiceColorCount)
}

//export GameGetCounterCount
func GameGetCounterCount(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	return C.int(len(h.Game.Counters))
}
