package interp

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
)

// order identifies the buff whose creation controls this hook. Effects with
// no order remain fixed pipeline hooks; priority defines effect categories.
func (rt *Runtime) hookOrder(v Value, kind engine.HookType) (func(*engine.EventContext) int, []int, error) {
	var ids []int
	replacement := false
	slotIDs := [2 * MaxChars]int{}
	for i := range slotIDs {
		slotIDs[i] = -1
	}
	scalar := -1
	playerIDs := [2]int{-1, -1}
	switch r := v.(type) {
	case *CounterProxy:
		scalar = r.ID
		ids = []int{r.ID}
		replacement = r.RefKind != RefKindNone
	case *PerPlayerProxy:
		playerIDs = r.IDs
		ids = r.AllCounterIDs()
		replacement = r.RefKind != RefKindNone
	case *PerCharProxy:
		slotIDs = r.IDs
		ids = r.AllCounterIDs()
		replacement = r.RefKind != RefKindNone
	case *SelfSlotProxy:
		slotIDs = r.SlotIDs
		for p := 0; p < 2; p++ {
			for c := 0; c < MaxChars; c++ {
				if r.SlotIDs[p*MaxChars+c] >= 0 {
					playerIDs[p] = r.SlotIDs[p*MaxChars+c]
					break
				}
			}
		}
		ids = r.AllCounterIDs()
		replacement = r.RefKind != RefKindNone
	default:
		return nil, nil, fmt.Errorf("hook order requires a counter")
	}
	for _, id := range ids {
		if id >= 0 {
			rt.Game.EnableCounterOrder(id, replacement)
			def := &rt.Game.BuffDefinitions[rt.Game.Counters[id].BuffIndex]
			for _, entry := range rt.Counters.TagGroups[1] { // Tag.Summon
				for _, counterID := range entry.CounterIDs {
					if counterID == id {
						def.Summon = true
					}
				}
			}
			found := false
			for _, source := range def.RuleSources {
				if source == rt.CurrentSourceFile {
					found = true
				}
			}
			if !found {
				def.RuleSources = append(def.RuleSources, rt.CurrentSourceFile)
			}
		}
	}
	return func(ctx *engine.EventContext) int {
		if scalar >= 0 {
			return scalar
		}
		p, c := ctx.ActorPlayer, ctx.ActorChar
		if kind == engine.HookDamageReduceBuff || kind == engine.HookShieldAbsorb || kind == engine.HookDamageImmunity {
			p, c = ctx.TargetPlayer, ctx.TargetChar
		}
		if p < 0 || p > 1 {
			return -1
		}
		if playerIDs[p] >= 0 {
			return playerIDs[p]
		}
		if c < 0 || c >= MaxChars {
			return -1
		}
		return slotIDs[p*MaxChars+c]
	}, ids, nil
}
