package tests

import (
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestDeferred_AfterDamageDrainsBothPaths(t *testing.T) {
	for _, absorb := range []bool{false, true} {
		t.Run(map[bool]string{false: "hit", true: "absorbed"}[absorb], func(t *testing.T) {
			env := NewGame(t, []string{"赤蝶"}, []string{"刻师傅"})
			g := env.G
			var events []string
			if absorb {
				g.Hooks.Register(engine.Hook{Type: engine.HookShieldAbsorb,
					Fn: func(g *engine.Game, ctx *engine.EventContext) { ctx.Value = 0 }})
			}
			g.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage,
				Fn: func(g *engine.Game, ctx *engine.EventContext) {
					events = append(events, "after")
					g.Defer(func(g *engine.Game) {
						events = append(events, "deferred")
						if g.CurrentEvent().Player != 1 {
							t.Fatal("lost actor frame")
						}
					})
				}})
			g.PushEvent(engine.EventFrame{Player: 1, Char: 0, ActionCtx: engine.ActUseSkill})
			hp := env.RT.Chars.BySlot[0][0].HPCounterID
			g.DealDamage(hp, engine.ElemPhysical, 1, engine.DamageOpts{ActorPlayer: 1, ActorChar: 0})
			g.PopEvent()
			if !reflect.DeepEqual(events, []string{"after", "deferred"}) {
				t.Fatalf("events=%v", events)
			}
		})
	}
}

func TestDeferred_ReentrantStackGrowthAndAppend(t *testing.T) {
	g := &engine.Game{}
	g.PushEvent(engine.EventFrame{})
	var order []int
	g.Defer(func(g *engine.Game) {
		order = append(order, 1)
		// Force the stack backing array to move, then append onto the original
		// frame. A retained pointer into the old array would lose or repeat work.
		for i := 0; i < 64; i++ {
			g.PushEvent(engine.EventFrame{})
		}
		for i := 0; i < 64; i++ {
			g.PopEvent()
		}
		g.Defer(func(g *engine.Game) { order = append(order, 3) })
	})
	g.Defer(func(g *engine.Game) { order = append(order, 2) })
	g.DrainDeferred()
	g.DrainDeferred()
	g.PopEvent()
	if !reflect.DeepEqual(order, []int{1, 2, 3}) {
		t.Fatalf("order=%v", order)
	}
}

func TestDeferred_SkillActionDrainsBeforeReturn(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 8})
	called := 0
	env.G.Hooks.Register(engine.Hook{Type: engine.HookSkillUse,
		Fn: func(g *engine.Game, ctx *engine.EventContext) { g.Defer(func(g *engine.Game) { called++ }) }})
	if !env.StepSkill("枪") {
		t.Fatal("attack unavailable")
	}
	if called != 1 {
		t.Fatalf("deferred callback count=%d", called)
	}
}
