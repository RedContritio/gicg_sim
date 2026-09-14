package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestNativeHaventLostRequiresOwnDeathAndResetsEachRound(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprintf("P%d", p), func(t *testing.T) {
			e := nativeTalentGame(t, "凯亚")
			name := "本大爷还没有输！"
			e.G.Turn = p
			e.giveCard(t, p, name)
			if e.FindAction(engine.ActionCard, name) >= 0 {
				t.Fatal("card playable without defeat")
			}
			nativeDamage(e, 1-p, 1, engine.ElemPiercing, 10)
			if e.FindAction(engine.ActionCard, name) >= 0 {
				t.Fatal("enemy defeat unlocked own card")
			}
			nativeDamage(e, p, 1, engine.ElemPiercing, 10)
			idx := e.FindAction(engine.ActionCard, name)
			if idx < 0 {
				t.Fatal("own defeat did not unlock card")
			}
			e.G.Step(idx)
			if e.DiceTotal(p) != 17 || e.Energy(p, 0) != 1 || e.G.Turn != p {
				t.Fatal("incorrect dice, energy, or turn after card")
			}
			e.giveCard(t, p, name)
			if e.FindAction(engine.ActionCard, name) >= 0 {
				t.Fatal("second copy playable in same round")
			}
			e.playToRoundEnd(t)
			e.G.GetLegalActions()
			e.G.Turn = p
			if e.FindAction(engine.ActionCard, name) >= 0 {
				t.Fatal("previous round defeat carried over")
			}
			nativeDamage(e, p, 2, engine.ElemPiercing, 10)
			if e.FindAction(engine.ActionCard, name) < 0 {
				t.Fatal("new round defeat did not reset allowance")
			}
		})
	}
}

func TestNativeSwitchCardsSurviveForcedSwitchAndConsumeOnAction(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprintf("P%d", p), func(t *testing.T) {
			e := nativeTalentGame(t, "凯亚")
			auditPlay(t, e, p, "换班时间")
			auditPlay(t, e, p, "交给我吧！")
			e.G.ForceSwitchTo(p, 1)
			for _, name := range []string{"换班时间", "交给我吧！"} {
				if e.G.Counters[findCounterIDPerPlayer(e, name+"_待生效", p)].Value != 1 {
					t.Fatal("forced switch consumed voluntary-switch buff")
				}
			}
			e.playToRoundEnd(t)
			e.G.GetLegalActions()
			e.SetDice(p, map[int]int{engine.DiceColorOmni: 16})
			auditSwitch(t, e, p, 0)
			if e.DiceTotal(p) != 16 || e.G.Turn != p {
				t.Fatal("next-round switch should be free and fast")
			}
			for _, name := range []string{"换班时间", "交给我吧！"} {
				if e.G.Counters[findCounterIDPerPlayer(e, name+"_待生效", p)].Value != 0 {
					t.Fatal("voluntary switch did not consume buff")
				}
			}
			auditSwitch(t, e, p, 1)
			if e.DiceTotal(p) != 15 || e.G.Turn != 1-p {
				t.Fatal("second switch must cost one die and be a battle action")
			}
		})
	}
}

func TestNativeCraneSwitchesAfterSkillDamageOnlyOnce(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprintf("P%d", p), func(t *testing.T) {
			e := nativeTalentGame(t, "凯亚")
			auditPlay(t, e, p, "鹤归之时")
			damaged := false
			e.G.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Fn: func(g *engine.Game, ctx *engine.EventContext) {
				if ctx.ActorPlayer == p && ctx.Source == engine.SrcSkill {
					damaged = true
					if g.Players[p].ActiveChar != 0 {
						t.Fatal("crane switched before original skill damage")
					}
				}
			}})
			auditSkill(t, e, p, "霜袭")
			if !damaged || e.G.Players[p].ActiveChar != 1 || e.G.Turn != 1-p {
				t.Fatal("crane failed to switch after skill")
			}
			if e.G.Counters[findCounterIDPerPlayer(e, "鹤归之时_待生效", p)].Value != 0 {
				t.Fatal("crane buff not consumed")
			}
		})
	}
}
