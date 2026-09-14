package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestCurrentRules_FoodSatiationIsPerTargetAndExpires(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, food := range []string{"美味烧鸡", "佛跳墙", "荷花酥"} {
			t.Run(fmt.Sprintf("P%d/%s", p, food), func(t *testing.T) {
				e := currentCardGame(t, p)
				auditPlay(t, e, p, food)
				e.giveCard(t, p, food)
				check := func(want0 bool) {
					t.Helper()
					seen := [2]bool{}
					for _, a := range e.G.GetLegalActions() {
						if a.Kind != engine.ActionCard || e.G.CardNames[e.G.Players[p].Hand[a.Index].Ref] != food {
							continue
						}
						if !a.HasTarget || a.TargetPlayer != p {
							t.Fatal("food offers enemy/missing target")
						}
						seen[a.TargetChar] = true
					}
					if seen != [2]bool{want0, true} {
						t.Fatalf("food targets=%v want [%t true]", seen, want0)
					}
				}
				check(false)
				e.playToRoundEnd(t)
				e.G.Turn = p
				e.SetDice(p, map[int]int{engine.DiceColorOmni: 8})
				check(true)
			})
		}
	}
}

func TestCurrentRules_FreeFastSwitchAndNextPaidSwitch(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			for _, name := range []string{"伏兵之术", "瞬身之术", "乘胜追击", "碌碌无为", "碌碌无为", "碌碌无为"} {
				auditPlay(t, e, p, name)
			}
			before := e.DiceTotal(p)
			auditSwitch(t, e, p, 1)
			if e.DiceTotal(p) != before || e.G.Turn != p {
				t.Fatal("first switch must be both free and fast")
			}
			count := findCounterIDPerPlayer(e, "乘胜追击_count", p)
			if e.G.ReadCounter(count) != 3 {
				t.Fatal("already-free switch counted")
			}
			for _, name := range []string{"伏兵之术_used", "瞬身之术_used"} {
				if e.G.ReadCounter(findCounterIDPerPlayer(e, name, p)) != 1 {
					t.Fatalf("%s not consumed", name)
				}
			}
			auditSwitch(t, e, p, 0)
			if e.DiceTotal(p) != before || e.G.Turn != 1-p || e.G.ReadCounter(count) != 4 {
				t.Fatal("second switch must use fourth-operation discount and be combat action")
			}
			auditSwitch(t, e, p, 1)
			if e.DiceTotal(p) != before-1 {
				t.Fatal("third switch should cost one")
			}
		})
	}
}

func TestCurrentRules_CleaningPreservesNonSummonStates(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "蝶鳞")
			auditSkill(t, e, p, "枪")
			auditPlay(t, e, p, "乘胜追击")
			auditPlay(t, e, p, "以牙还牙")
			e.SetDice(p, map[int]int{engine.DiceColorOmni: 8})
			auditPlay(t, e, p, "清洁时间")
			if e.G.ReadCounter(findCounterIDPerPlayer(e, "以牙还牙_rounds", p)) != 0 {
				t.Fatal("summon not cleared")
			}
			if e.counterByChar("蝶印", 1-p, 0) != 1 || e.counterByChar("蝶火_active", p, 0) != 1 || e.G.ReadCounter(findCounterIDPerPlayer(e, "乘胜追击_active", p)) != 1 {
				t.Fatal("cleaning erased non-summon state")
			}
			before := e.HP(1-p, 0)
			e.playToRoundEnd(t)
			if e.HP(1-p, 0) != before-1 || e.counterByChar("蝶印", 1-p, 0) != 0 {
				t.Fatal("surviving mark should tick once")
			}
		})
	}
}
