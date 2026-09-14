package engine

import "testing"

func TestRecreatedBuffWaitsForNextEvent(t *testing.T) {
	g := &Game{Hooks: NewHookRegistry()}
	id := g.CreateCounter(0, 0, 1)
	g.EnableCounterOrder(id, false)
	g.WriteCounter(id, OpSet, 1)
	old := g.Buffs[0].ID
	replace := true
	g.Hooks.Register(Hook{Type: HookDamageAdd, Fn: func(g *Game, ctx *EventContext) {
		if replace {
			g.WriteCounter(id, OpSet, 0)
			g.WriteCounter(id, OpSet, 1)
			replace = false
		}
	}})
	fired := 0
	g.Hooks.Register(Hook{Type: HookDamageAdd, OrderCounter: func(*EventContext) int { return id }, Fn: func(*Game, *EventContext) { fired++ }})
	g.FireEventHooks(HookDamageAdd, &EventContext{})
	if fired != 0 || g.Buffs[0].ID == old {
		t.Fatal("new lifecycle was mistaken for the eligible old instance")
	}
	g.FireEventHooks(HookDamageAdd, &EventContext{})
	if fired != 1 {
		t.Fatal("new instance did not participate in the next event")
	}
}
