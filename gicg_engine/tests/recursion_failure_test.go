package tests

import (
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

// Reaching a recursion guard must abort the sample, never manufacture a
// successful transition with the remaining effects silently discarded.
func TestRuleFailure_RecursiveEffectsAbort(t *testing.T) {
	for _, kind := range []string{"counter", "damage"} {
		t.Run(kind, func(t *testing.T) {
			env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
			g := env.G
			cid := g.CreateCounter(0, 0, 1000)
			var run func()
			if kind == "counter" {
				g.Hooks.Register(engine.Hook{Type: engine.HookAfterWrite, CounterID: cid, Op: engine.OpAdd,
					Fn: func(g *engine.Game, _ *engine.EventContext) { g.WriteCounter(cid, engine.OpAdd, 1) }})
				run = func() { g.WriteCounter(cid, engine.OpAdd, 1) }
			} else {
				hp := env.RT.Chars.BySlot[1][0].HPCounterID
				g.Hooks.Register(engine.Hook{Type: engine.HookDamageAdd,
					Fn: func(g *engine.Game, _ *engine.EventContext) {
						g.DealDamage(hp, engine.ElemPhysical, 1, engine.DamageOpts{ActorPlayer: 0, ActorChar: 0})
					}})
				run = func() {
					g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
					defer g.PopEvent()
					g.DealDamage(hp, engine.ElemPhysical, 1, engine.DamageOpts{ActorPlayer: 0, ActorChar: 0})
				}
			}
			var recovered any
			func() { defer func() { recovered = recover() }(); run() }()
			err, ok := recovered.(*engine.RuleError)
			if !ok || !strings.Contains(err.Error(), "depth") {
				t.Fatalf("expected typed depth failure, got %v", recovered)
			}
			if g.Failure != err || g.Depth() != 0 || g.IsQuiescent() {
				t.Fatalf("failure not sticky or recursion not unwound: depth=%d", g.Depth())
			}
			g.ResetDynamicState(7)
			if g.Failure != nil || !g.IsQuiescent() {
				t.Fatal("reset did not recover the failed engine")
			}
		})
	}
}
