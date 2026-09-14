package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"testing"
)

// Expectations are hand-derived in freeze-current-rule-baseline/interactions.md.
func TestCurrentRules_CostPenaltyRestrictedFirst(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			e.SetDice(1-p, map[int]int{engine.DiceColorOmni: 16})
			auditPlay(t, e, 1-p, "反制")
			auditPlay(t, e, p, "乘胜追击")
			for i := 0; i < 3; i++ {
				auditPlay(t, e, p, "碌碌无为")
			}
			// (1 fire + 2 any) + 1 any - 3 restricted-first = 1 any.
			// Only water dice remain: a surviving fire requirement would make it illegal.
			e.SetDice(p, map[int]int{engine.DiceColorWater: 1})
			for i := 0; i < 3; i++ {
				e.G.GetLegalActions()
			}
			if e.counterByChar("反制_debuff", p, 0) != 1 {
				t.Fatal("query consumed penalty")
			}
			auditSkill(t, e, p, "枪")
			if e.DiceTotal(p) != 0 || e.counterByChar("反制_debuff", p, 0) != 0 {
				t.Fatal("penalty/discount payment or consumption incorrect")
			}
			if e.G.ReadCounter(findCounterIDPerPlayer(e, "乘胜追击_count", p)) != 4 {
				t.Fatal("fourth action counted incorrectly")
			}
		})
	}
}

func TestCurrentRules_FreeTalentStillPaysEnergyOnce(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p, []string{"墨客", "赤蝶"}, []string{"赤蝶", "墨客"})
			auditPlay(t, e, p, "乘胜追击")
			for i := 0; i < 3; i++ {
				auditPlay(t, e, p, "碌碌无为")
			}
			e.SetDice(p, map[int]int{})
			c := e.RT.Chars.BySlot[p][0]
			e.G.Counters[c.EnergyCounterID].Value = 1
			e.giveCard(t, p, "守正")
			if e.FindAction(engine.ActionCard, "守正") >= 0 {
				t.Fatal("dice discount bypassed energy requirement")
			}
			e.G.Counters[c.EnergyCounterID].Value = 2
			idx := e.FindAction(engine.ActionCard, "守正")
			if idx < 0 {
				t.Fatal("discounted talent unavailable")
			}
			e.Step(idx)
			if e.Energy(p, 0) != 0 || e.DiceTotal(p) != 0 || e.HP(1-p, 0) != 13 {
				t.Fatal("talent payment or invoked effect wrong")
			}
			if e.G.ReadCounter(findCounterIDPerPlayer(e, "乘胜追击_count", p)) != 4 {
				t.Fatal("invoked skill double-counted operation")
			}
		})
	}
}

func TestCurrentRules_AddMultiplyThenReaction(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditSkill(t, e, p, "蝶火")
			auditPlay(t, e, p, "佛跳墙")
			auditPlay(t, e, p, "测试卡_增幅")
			e.setBuffToOne(t, "水元素附着", 1-p, 0)
			auditSkill(t, e, p, "枪")
			// (normal 2 + infusion 2 + food 2) * 2 + vaporize 2 = 14.
			if e.HP(1-p, 0) != 1 {
				t.Fatalf("enemy HP=%d want 1", e.HP(1-p, 0))
			}
			if e.counterByChar("佛跳墙_buff", p, 0) != 0 || e.G.ReadCounter(findCounterIDPerPlayer(e, "测试卡_增幅_buff", p)) != 0 {
				t.Fatal("one-shot effects not consumed")
			}
			if e.counterByChar("水元素附着", 1-p, 0) != 0 {
				t.Fatal("reaction did not consume water")
			}
		})
	}
}

func TestCurrentRules_LotusBeforeShield(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p, []string{"猫咪"}, []string{"赤蝶"})
			auditSkill(t, e, p, "猫爪护盾")
			auditPlay(t, e, p, "荷花酥")
			hp := e.RT.Chars.BySlot[p][0].HPCounterID
			for i, n := range []int{3, 2, 1} {
				e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
					g.DealDamage(hp, engine.ElemPhysical, n, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
				})
				wantHP := 15
				if i == 2 {
					wantHP = 14
				}
				wantShield := 0
				if i == 0 {
					wantShield = 2
				}
				if e.HP(p, 0) != wantHP || e.counterByChar("猫爪护盾", p, 0) != wantShield {
					t.Fatalf("hit %d: hp=%d shield=%d", i, e.HP(p, 0), e.counterByChar("猫爪护盾", p, 0))
				}
				if e.counterByChar("荷花酥_buff", p, 0) != 0 {
					t.Fatal("lotus not consumed")
				}
			}
		})
	}
}

func TestCurrentRules_LotusRetaliatesOnce(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "以逸待劳")
			auditPlay(t, e, p, "荷花酥")
			hp := e.RT.Chars.BySlot[p][0].HPCounterID
			for i := 0; i < 2; i++ {
				e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
					g.DealDamage(hp, engine.ElemPhysical, 3, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
				})
				want := 15
				if i == 1 {
					want = 12
				}
				if e.HP(p, 0) != want || e.HP(1-p, 0) != 12 {
					t.Fatalf("hit %d: own=%d enemy=%d", i, e.HP(p, 0), e.HP(1-p, 0))
				}
			}
		})
	}
}
