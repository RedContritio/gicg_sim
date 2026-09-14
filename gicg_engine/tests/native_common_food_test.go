package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func nativePlayTarget(t *testing.T, e *GameEnv, p, target int, name string) {
	t.Helper()
	e.G.Turn = p
	e.giveCard(t, p, name)
	for i, a := range e.G.GetLegalActions() {
		if a.Kind == engine.ActionCard && a.HasTarget && a.TargetPlayer == p && a.TargetChar == target &&
			e.G.CardNames[e.G.Players[p].Hand[a.Index].Ref] == name {
			if e.G.Step(i) == engine.StepNeedTarget {
				t.Fatal("targeted card unexpectedly requested input")
			}
			return
		}
	}
	t.Fatalf("%s unavailable for P%d character %d", name, p, target)
}

func TestNativeFoodHealingAndSatiety(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, c := range []int{0, 1} {
			for _, spec := range []struct {
				name       string
				heal, cost int
			}{{"甜甜花酿鸡", 1, 0}, {"蒙德土豆饼", 2, 1}, {"烤蘑菇披萨", 1, 1}} {
				t.Run(fmt.Sprintf("%s_P%d_C%d", spec.name, p, c), func(t *testing.T) {
					e := nativeTalentGame(t, "凯亚")
					e.G.WriteCounter(e.RT.Chars.BySlot[p][c].HPCounterID, engine.OpSet, 5)
					nativePlayTarget(t, e, p, c, spec.name)
					if e.HP(p, c) != 5+spec.heal || e.DiceTotal(p) != 16-spec.cost || e.G.Turn != p {
						t.Fatal("incorrect healing, cost, or fast-action turn")
					}
					e.giveCard(t, p, "甜甜花酿鸡")
					for _, a := range e.G.GetLegalActions() {
						if a.Kind == engine.ActionCard && a.TargetChar == c {
							t.Fatal("satiated character can eat another food")
						}
					}
					if spec.name == "烤蘑菇披萨" {
						for round := 1; round <= 3; round++ {
							e.playToRoundEnd(t)
							want := 6 + min(round, 2)
							if e.HP(p, c) != want {
								t.Fatalf("pizza round %d HP=%d want=%d", round, e.HP(p, c), want)
							}
						}
					}
				})
			}
		}
	}
}

func TestNativeLotusPreservedByPiercingThenConsumedOnce(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, c := range []int{0, 1} {
			t.Run(fmt.Sprintf("P%d_C%d", p, c), func(t *testing.T) {
				e := nativeTalentGame(t, "凯亚")
				nativePlayTarget(t, e, p, c, "莲花酥")
				before := e.HP(p, c)
				nativeDamage(e, p, c, engine.ElemPiercing, 1)
				if e.HP(p, c) != before-1 || e.counterByChar("莲花酥_状态", p, c) != 1 {
					t.Fatal("piercing consumed lotus")
				}
				nativeDamage(e, p, c, engine.ElemPhysical, 4)
				if e.HP(p, c) != before-2 || e.counterByChar("莲花酥_状态", p, c) != 0 {
					t.Fatal("lotus did not reduce ordinary damage by 3")
				}
				nativeDamage(e, p, c, engine.ElemPhysical, 1)
				if e.HP(p, c) != before-3 {
					t.Fatal("lotus applied more than once")
				}
			})
		}
	}
}

func TestNativeNormalAttackFoodCharges(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, spec := range []struct {
			name string
			uses int
		}{{"北地烟熏鸡", 1}, {"兽肉薄荷卷", 3}} {
			t.Run(fmt.Sprintf("%s_P%d", spec.name, p), func(t *testing.T) {
				e := nativeTalentGame(t, "凯亚")
				nativePlayTarget(t, e, p, 0, spec.name)
				auditSkill(t, e, p, "霜袭")
				if e.counterByChar(spec.name+"_次数", p, 0) != spec.uses {
					t.Fatal("elemental skill consumed normal-attack discount")
				}
				for n := 0; n <= spec.uses; n++ {
					e.G.WriteCounter(e.RT.Chars.BySlot[1-p][0].HPCounterID, engine.OpSet, 10)
					e.SetDice(p, map[int]int{engine.DiceColorOmni: 16})
					auditSkill(t, e, p, "仪典剑术")
					want := 2
					if n == spec.uses {
						want = 3
					}
					if 16-e.DiceTotal(p) != want || e.counterByChar(spec.name+"_次数", p, 0) != max(0, spec.uses-n-1) {
						t.Fatalf("attack %d has wrong discount or remaining charges", n+1)
					}
				}
			})
		}
	}
}
