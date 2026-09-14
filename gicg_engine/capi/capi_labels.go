package main

/*
#include <stdlib.h>
#include <string.h>
*/
import "C"

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"strings"
	"unsafe"
)

// Label / util C exports: current round, card names, action labels,
// counter slot labels, hook labels, FreeString, GetDynamicObs,
// ForcedSwitchPending, main. Replay / view-export C exports live in
// capi_replay.go.

//export GameGetCurrentRound
func GameGetCurrentRound(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	return C.int(h.Game.Round)
}

// Returns newline-joined "ref\tname" pairs for every declared card.
// Used by Python wrappers to translate card names <-> refs once at
// init time. Caller must free with GameFreeString.
//
//export GameGetCardNames
func GameGetCardNames(id C.int) *C.char {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return nil
	}
	var lines []string
	for ref, name := range h.Game.CardNames {
		lines = append(lines, fmt.Sprintf("%d\t%s", ref, name))
	}
	return C.CString(strings.Join(lines, "\n"))
}

// Returns newline-joined labels for the *current* legal actions, in the same
// order as GameGetLegalActions. Format per line: "<kind>\t<name>\t<slot>"
// where kind is Skill/Card/Switch/EndTurn/Tune/Reroll, name is the resolved DSL name
// (or numeric fallback if unknown), and slot is:
//
//   - ActionCard:   hand index (0..len(Hand)-1) — disambiguates same-named
//     duplicates when multiple copies share a card ref.
//   - ActionTune:   hand index of the discarded card.
//   - ActionSwitch: target char slot (0..len(Chars)-1).
//   - ActionSkill / ActionEndTurn / ActionReroll / other: -1.
//
// Caller must free with GameFreeString.
//
//export GameGetActionLabels
func GameGetActionLabels(id C.int) *C.char {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return nil
	}
	g := h.Game
	actions := g.GetLegalActions()
	lines := make([]string, 0, len(actions))
	for _, a := range actions {
		var kind, name string
		slot := -1
		switch a.Kind {
		case engine.ActionReroll:
			kind = "Reroll"
			name = fmt.Sprintf("颜色%d 重投%d枚", a.RerollColor, a.Index)
			if a.RerollColor == engine.DiceColorCount {
				name = "确认重投"
			}
		case engine.ActionSkill:
			kind = "Skill"
			name = g.SkillNames[a.Index]
			if name == "" {
				name = fmt.Sprintf("skill#%d", a.Index)
			}
		case engine.ActionCard:
			kind = "Card"
			p := &g.Players[a.PlayerIdx]
			if a.Index >= 0 && a.Index < len(p.Hand) {
				name = g.CardNames[p.Hand[a.Index].Ref]
				slot = a.Index
			}
			if name == "" {
				name = fmt.Sprintf("card#%d", a.Index)
			}
		case engine.ActionSwitch:
			kind = "Switch"
			p := &g.Players[a.PlayerIdx]
			if a.Index >= 0 && a.Index < len(p.Chars) {
				name = g.CharNames[[2]int{a.PlayerIdx, a.Index}]
				slot = a.Index
			}
			if name == "" {
				name = fmt.Sprintf("char#%d", a.Index)
			}
		case engine.ActionEndTurn:
			kind = "EndTurn"
			name = "-"
		case engine.ActionTune:
			kind = "Tune"
			p := &g.Players[a.PlayerIdx]
			if a.Index >= 0 && a.Index < len(p.Hand) {
				name = g.CardNames[p.Hand[a.Index].Ref]
				slot = a.Index
			}
			if name == "" {
				name = fmt.Sprintf("tune#%d", a.Index)
			}
		default:
			kind = "?"
			name = "-"
		}
		lines = append(lines, fmt.Sprintf("%s\t%s\t%d", kind, name, slot))
	}
	return C.CString(strings.Join(lines, "\n"))
}

// Returns newline-joined labels (one per observation counter slot) as a
// null-terminated C string. Caller must free with GameFreeString.
//
//export GameGetActiveCounterSlotLabels
func GameGetActiveCounterSlotLabels(id C.int) *C.char {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return nil
	}
	labels := h.Game.ActiveCounterSlotLabels()
	return C.CString(strings.Join(labels, "\n"))
}

// Returns newline-joined labels as a null-terminated C string. Caller must
// free the returned pointer with GameFreeString. Used by the checkpoint visualizer
// to annotate attention plots with semantic hook names.
//
//export GameGetActiveHookLabels
func GameGetActiveHookLabels(id C.int) *C.char {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return nil
	}
	labels := h.Game.ActiveHookLabels()
	joined := strings.Join(labels, "\n")
	return C.CString(joined)
}

//export GameFreeString
func GameFreeString(s *C.char) {
	C.free(unsafe.Pointer(s))
}

//export GameGetDynamicObs
func GameGetDynamicObs(id C.int, perspective C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	obs := h.Game.BuildDynamicObs(int(perspective))
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), len(obs))
	for i, v := range obs {
		arr[i] = C.int(v)
	}
}

// Returns 1 if the engine is currently waiting for a forced switch (e.g.
// death, overload) from the given player, else 0.
//
//export GameIsForcedSwitchPending
func GameIsForcedSwitchPending(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return 0
	}
	g := h.Game
	if g.PendingAction != nil && g.PendingAction.Kind == engine.ActionSwitch {
		return 1
	}
	return 0
}

func main() {}
