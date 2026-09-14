package audit

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
)

func modifier(kind engine.HookType) bool {
	switch kind {
	case engine.HookReactionDamage, engine.HookActionPrepare, engine.HookDamageType, engine.HookDamageAdd, engine.HookDamageMul,
		engine.HookDamageReduceBuff, engine.HookShieldAbsorb, engine.HookDamageImmunity,
		engine.HookAfterDamage, engine.HookBeforeHeal, engine.HookAfterHeal, engine.HookAfterEnergyGain,
		engine.HookBeforeTurnFlip:
		return true
	}
	return false
}

// Catch modifiers omitted from both register_buff and order. Auxiliary counters
// read by an explicitly bound effect remain ordinary observable counter state.
func untracked(g *engine.Game) []string {
	var issues []string
	for _, h := range g.Hooks.AllHooks() {
		if h.OrderCounter != nil || !modifier(h.Type) || structural(h) {
			continue
		}
		for _, a := range h.CounterAccess {
			if a.Method != "get" && a.Method != "get_at" {
				continue
			}
			for _, id := range a.CounterIDs {
				if id >= 0 && g.Counters[id].BuffIndex < 0 {
					issues = append(issues, fmt.Sprintf("untracked modifier counter: %s:%d %s / %s", h.Source, a.Line, a.Symbol, g.CounterNames[id]))
				}
			}
		}
	}
	return issues
}
