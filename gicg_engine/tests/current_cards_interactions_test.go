package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func auditSkill(t *testing.T, e *GameEnv, p int, name string) {
	t.Helper()
	e.G.Turn = p
	if !e.StepSkill(name) {
		t.Fatalf("%s unavailable", name)
	}
}

func auditSwitch(t *testing.T, e *GameEnv, p, c int) {
	t.Helper()
	e.G.Turn = p
	for i, a := range e.G.GetLegalActions() {
		if a.Kind == engine.ActionSwitch && a.Index == c {
			e.G.Step(i)
			return
		}
	}
	t.Fatal("switch unavailable")
}

func TestCurrentCards_FoodAndAmplification(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, name := range []string{"佛跳墙", "速速茶点", "测试卡_增幅"} {
			t.Run(fmt.Sprintf("P%d/%s", p, name), func(t *testing.T) {
				e := currentCardGame(t, p)
				auditPlay(t, e, p, name)
				if name == "测试卡_增幅" {
					auditPlay(t, e, p, "测试卡_碎片")
				}
				for n := 0; n < 3; n++ {
					hp, dice := e.HP(1-p, 0), e.DiceTotal(p)
					auditSkill(t, e, p, "枪")
					damage, cost := 2, 3
					if n == 0 && name != "速速茶点" {
						damage = 4
					}
					if n < 2 && name == "速速茶点" {
						cost = 2
					}
					if got := hp - e.HP(1-p, 0); got != damage {
						t.Fatalf("hit %d damage=%d want %d", n, got, damage)
					}
					if got := dice - e.DiceTotal(p); got != cost {
						t.Fatalf("hit %d cost=%d want %d", n, got, cost)
					}
				}
			})
		}
	}
}

func TestCurrentCards_LotusThresholdAndConsumption(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "荷花酥")
			hp := e.RT.Chars.BySlot[p][0].HPCounterID
			for i, damage := range []int{2, 3, 3} {
				before := e.HP(p, 0)
				e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
					g.DealDamage(hp, engine.ElemPhysical, damage, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
				})
				want := damage
				if i == 1 {
					want = 0
				}
				if got := before - e.HP(p, 0); got != want {
					t.Fatalf("hit %d damage=%d want %d", i, got, want)
				}
			}
		})
	}
}

func TestCurrentCards_SwitchCardsBothSeats(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, name := range []string{"伏兵之术", "瞬身之术"} {
			t.Run(fmt.Sprintf("P%d/%s", p, name), func(t *testing.T) {
				e := currentCardGame(t, p)
				auditPlay(t, e, p, name)
				for n := 0; n < 2; n++ {
					before := e.DiceTotal(p)
					auditSwitch(t, e, p, 1-n)
					cost, turn := 1, 1-p
					if n == 0 && name == "伏兵之术" {
						cost = 0
					}
					if n == 0 && name == "瞬身之术" {
						turn = p
					}
					if before-e.DiceTotal(p) != cost || e.G.Turn != turn {
						t.Fatalf("switch %d: cost=%d turn=%d want %d/%d", n, before-e.DiceTotal(p), e.G.Turn, cost, turn)
					}
				}
			})
		}
	}
}

func TestCurrentCards_CleaningRemovesBothSummons(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			e.SetDice(1-p, map[int]int{engine.DiceColorOmni: 16})
			auditPlay(t, e, p, "以牙还牙")
			auditPlay(t, e, 1-p, "以牙还牙")
			auditPlay(t, e, p, "清洁时间")
			for side := 0; side < 2; side++ {
				if e.G.Counters[findCounterIDPerPlayer(e, "以牙还牙_rounds", side)].Value != 0 {
					t.Fatal("summon survived cleaning")
				}
			}
			before := [2]int{e.HP(0, 0), e.HP(1, 0)}
			e.playToRoundEnd(t)
			if e.HP(0, 0) != before[0] || e.HP(1, 0) != before[1] {
				t.Fatal("removed summon still dealt damage")
			}
		})
	}
}

func TestCurrentCards_OffenseConvertsShieldOverflow(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p, []string{"猫咪"}, []string{"赤蝶"})
			auditPlay(t, e, p, "以攻代守")
			auditSkill(t, e, p, "猫爪护盾")
			if e.HP(1-p, 0) != 13 {
				t.Fatalf("enemy HP=%d want 13 (1 ice + 1 overflow)", e.HP(1-p, 0))
			}
			if e.counterByChar("猫爪护盾", p, 0) != 1 {
				t.Fatal("shield must retain exactly one point")
			}
			if e.HP(p, 0) != 15 {
				t.Fatalf("owner HP=%d changed", e.HP(p, 0))
			}
		})
	}
}

func TestCurrentCards_FavoniusBothSeats(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, name := range []string{"西风长枪", "西风剑"} {
			t.Run(fmt.Sprintf("P%d/%s", p, name), func(t *testing.T) {
				e := currentCardGame(t, p)
				auditPlay(t, e, p, name)
				if name == "西风长枪" {
					auditSkill(t, e, p, "枪")
					if e.Energy(p, 0) != 1 || e.Energy(p, 1) != 1 {
						t.Fatal("energy was not shared")
					}
					auditSkill(t, e, p, "枪")
					if e.Energy(p, 0) != 3 || e.Energy(p, 1) != 2 {
						t.Fatal("second skill bonus or energy cap wrong")
					}
				} else {
					auditSwitch(t, e, p, 1)
					before := e.HP(1-p, 0)
					auditSkill(t, e, p, "剑")
					if before-e.HP(1-p, 0) != 3 {
						t.Fatal("sword should add one damage")
					}
					auditSwitch(t, e, p, 0)
					auditSkill(t, e, p, "枪")
					if e.Energy(p, 0) != 2 {
						t.Fatal("next character did not gain one bonus energy")
					}
				}
			})
		}
	}
}
