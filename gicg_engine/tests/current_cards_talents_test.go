package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestCurrentCards_MoKeSkillsBothSeats(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditSwitch(t, e, p, 1)
			auditSkill(t, e, p, "墨意")
			if e.HP(1-p, 0) != 14 || e.counterByChar("水云", p, 1) != 2 {
				t.Fatal("墨意 must deal 1 water damage and add 2 水云")
			}
			hp := e.RT.Chars.BySlot[p][1].HPCounterID
			e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
				g.DealDamage(hp, engine.ElemPhysical, 3, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
			})
			if e.HP(p, 1) != 13 || e.counterByChar("水云", p, 1) != 1 {
				t.Fatal("水云 must reduce 3 damage to 2 and consume one")
			}
			e.G.Counters[e.RT.Chars.BySlot[p][1].EnergyCounterID].Value = 2
			auditSkill(t, e, p, "水龙吟")
			if e.Energy(p, 1) != 0 || e.G.ReadCounter(findCounterIDPerPlayer(e, "泼墨", p)) != 2 {
				t.Fatal("水龙吟 payment or charges wrong")
			}
			before := e.HP(1-p, 0)
			auditSkill(t, e, p, "剑")
			if before-e.HP(1-p, 0) != 4 || e.G.ReadCounter(findCounterIDPerPlayer(e, "泼墨", p)) != 1 {
				t.Fatal("剑 must deal 2 physical plus one 2-water followup")
			}
		})
	}
}

func TestCurrentCards_ShouZhengPaysEnergyExactlyOnce(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditSwitch(t, e, p, 1)
			e.G.Turn = p
			e.giveCard(t, p, "守正")
			id := e.RT.Chars.BySlot[p][1].EnergyCounterID
			for energy := 0; energy < 2; energy++ {
				e.G.Counters[id].Value = energy
				if e.FindAction(engine.ActionCard, "守正") >= 0 {
					t.Fatalf("offered with only %d energy", energy)
				}
			}
			e.G.Counters[id].Value = 2
			idx := e.FindAction(engine.ActionCard, "守正")
			if idx < 0 {
				t.Fatal("unavailable with required energy")
			}
			before := e.DiceTotal(p)
			e.G.Step(idx)
			if e.Energy(p, 1) != 0 || before-e.DiceTotal(p) != 3 {
				t.Fatalf("wrong payment: energy=%d dice=%d", e.Energy(p, 1), before-e.DiceTotal(p))
			}
			if e.HP(1-p, 0) != 13 {
				t.Fatal("on-cast damage must be exactly 2")
			}
			if e.G.ReadCounter(findCounterIDPerPlayer(e, "泼墨", p)) != 2 {
				t.Fatal("burst did not grant two charges")
			}
		})
	}
}

func TestCurrentCards_ShouZhengProtectsWaterCloud(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditSwitch(t, e, p, 1)
			auditSkill(t, e, p, "墨意")
			e.G.Counters[e.RT.Chars.BySlot[p][1].EnergyCounterID].Value = 2
			auditPlay(t, e, p, "守正")
			auditSkill(t, e, p, "剑")
			if e.counterByChar("正气", p, 1) != 1 {
				t.Fatal("泼墨 consumption did not grant 正气")
			}
			before := e.HP(p, 1)
			hp := e.RT.Chars.BySlot[p][1].HPCounterID
			e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
				g.DealDamage(hp, engine.ElemPhysical, 3, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
			})
			if before-e.HP(p, 1) != 2 || e.counterByChar("水云", p, 1) != 2 || e.counterByChar("正气", p, 1) != 0 {
				t.Fatal("正气 must pay for water-cloud reduction without consuming 水云")
			}
		})
	}
}

func TestCurrentCards_DieLinHealingThreshold(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, talent := range []bool{false, true} {
			for _, hp := range []int{5, 7, 8} {
				t.Run(fmt.Sprintf("P%d/talent=%t/hp=%d", p, talent, hp), func(t *testing.T) {
					e := currentCardGame(t, p)
					if talent {
						auditPlay(t, e, p, "蝶鳞")
					} else {
						auditSkill(t, e, p, "蝶火")
					}
					c := e.RT.Chars.BySlot[p][0]
					e.G.Counters[c.HPCounterID].Value = hp
					e.G.Counters[c.EnergyCounterID].Value = 3
					auditSkill(t, e, p, "回火")
					want := hp
					if hp < 8 {
						want += 4
						if talent {
							want++
						}
					}
					if e.HP(p, 0) != want {
						t.Fatalf("HP=%d want %d", e.HP(p, 0), want)
					}
					if e.Energy(p, 0) != 0 {
						t.Fatal("burst energy not paid")
					}
				})
			}
		}
	}
}
