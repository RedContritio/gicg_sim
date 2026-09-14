package interp

import engine "gicg_mono/gicg_engine"

// Card costs are paid once by the card; invoked skills carry Paid=true.
func (rt *Runtime) registerCardEnergy(entry *CardRef) {
	if entry.Cost.Energy <= 0 {
		return
	}
	rt.registerHook(engine.Hook{Type: engine.HookActionCheck, Fn: func(g *engine.Game, ctx *engine.EventContext) {
		if ctx.ActionKind != engine.ActionCard || ctx.CardRef != entry.Ref {
			return
		}
		c := rt.Chars.BySlot[ctx.ActorPlayer][ctx.ActorChar]
		if c == nil || c.EnergyCounterID < 0 || g.ReadCounter(c.EnergyCounterID) < entry.Cost.Energy {
			ctx.Playable = false
		}
	}})
	rt.registerHook(engine.Hook{Type: engine.HookActionPrepare, Fn: func(g *engine.Game, ctx *engine.EventContext) {
		if ctx.ActionKind == engine.ActionCard && ctx.CardRef == entry.Ref {
			ctx.EnergyCost = entry.Cost.Energy
		}
	}})
	rt.registerHook(engine.Hook{Type: engine.HookCardPlay, Priority: 1000, Fn: func(g *engine.Game, ctx *engine.EventContext) {
		if ctx.CardRef != entry.Ref {
			return
		}
		c := rt.Chars.BySlot[ctx.ActorPlayer][ctx.ActorChar]
		g.ConsumeEnergy(c.EnergyCounterID, entry.Cost.Energy)
	}})
}
