package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestNativeBackgroundOverloadNeverSwitchesActive(t *testing.T) {
	for _, player := range []int{0, 1} {
		for _, target := range []int{1, 2} {
			for _, lethal := range []bool{false, true} {
				for _, elem := range []engine.Element{engine.ElemFire, engine.ElemElectro} {
					t.Run(fmt.Sprintf("P%d_slot%d_lethal%t_element%d", player, target, lethal, elem), func(t *testing.T) {
						e := nativeTalentGame(t, "凯亚")
						aura := "雷元素附着"
						if elem == engine.ElemElectro {
							aura = "火元素附着"
						}
						setNativeAura(t, e, aura, player, target)
						hp := e.RT.Chars.BySlot[player][target].HPCounterID
						if lethal {
							e.G.Counters[hp].Value = 2
						}
						before := e.G.Counters[hp].Value
						turn, paid := e.G.Turn, e.G.DicePaid
						switches := 0
						e.G.Hooks.Register(engine.Hook{Type: engine.HookSwitch, Fn: func(_ *engine.Game, _ *engine.EventContext) { switches++ }})
						result := e.G.ExecuteEffect(engine.EventFrame{Player: 1 - player, Char: 0, Source: engine.SrcSkill}, func(g *engine.Game) {
							g.DealDamage(hp, elem, 1, engine.DamageOpts{ActorPlayer: 1 - player, ActorChar: 0})
						})
						if result != engine.StepContinue || e.G.HasPending() || e.G.Players[player].ActiveChar != 0 || switches != 0 {
							t.Fatal("background overload switched active or requested replacement")
						}
						if e.G.Counters[hp].Value != max(0, before-3) || e.G.Turn != turn || e.G.DicePaid != paid {
							t.Fatal("background overload lost damage bonus or changed action ownership/payment")
						}
					})
				}
			}
		}
	}
}

func TestNativeLethalOverloadWrapsAndSkipsDead(t *testing.T) {
	for _, player := range []int{0, 1} {
		for _, elem := range []engine.Element{engine.ElemFire, engine.ElemElectro} {
			for _, start := range []int{0, 2} {
				t.Run(fmt.Sprintf("P%d_element%d_start%d", player, elem, start), func(t *testing.T) {
					e := nativeTalentGame(t, "凯亚")
					if start == 2 {
						e.G.ExecuteEffect(engine.EventFrame{Player: player, Char: 0}, func(g *engine.Game) { g.ForceSwitchTo(player, 2) })
					}
					// Kill the middle background character without a reaction.
					middle := e.RT.Chars.BySlot[player][1].HPCounterID
					e.G.ExecuteEffect(engine.EventFrame{Player: 1 - player, Char: 0}, func(g *engine.Game) {
						g.DealDamage(middle, engine.ElemPhysical, 99, engine.DamageOpts{ActorPlayer: 1 - player, ActorChar: 0})
					})
					aura := "雷元素附着"
					if elem == engine.ElemElectro {
						aura = "火元素附着"
					}
					setNativeAura(t, e, aura, player, start)
					hp := e.RT.Chars.BySlot[player][start].HPCounterID
					switches := 0
					e.G.Hooks.Register(engine.Hook{Type: engine.HookSwitch, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
						if ctx.ActionCtx != engine.ActForcedReaction {
							t.Error("wrong switch semantics")
						}
						switches++
					}})
					result := e.G.ExecuteEffect(engine.EventFrame{Player: 1 - player, Char: 0}, func(g *engine.Game) {
						g.DealDamage(hp, elem, 99, engine.DamageOpts{ActorPlayer: 1 - player, ActorChar: 0})
					})
					if result != engine.StepContinue || e.G.HasPending() || e.G.Players[player].ActiveChar != 2-start || switches != 1 {
						t.Fatal("overload failed wrap/skip or produced duplicate replacement")
					}
				})
			}
		}
	}
}

func TestNativeOrdinaryLethalHitStillRequestsChoice(t *testing.T) {
	e := nativeTalentGame(t, "凯亚")
	hp := e.RT.Chars.BySlot[1][0].HPCounterID
	result := e.G.ExecuteEffect(engine.EventFrame{Player: 0, Char: 0}, func(g *engine.Game) {
		g.DealDamage(hp, engine.ElemPhysical, 99, engine.DamageOpts{ActorPlayer: 0, ActorChar: 0})
	})
	if result != engine.StepNeedTarget || !e.G.HasPending() || len(e.G.GetLegalActions()) != 2 {
		t.Fatal("ordinary death must retain player choice")
	}
}
