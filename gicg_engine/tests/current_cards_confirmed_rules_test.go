package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestCurrentCards_ChengShengFourthPaidOperation(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, kind := range []string{"card", "normal", "elemental", "same", "switch"} {
			t.Run(fmt.Sprintf("P%d/%s", p, kind), func(t *testing.T) {
				e := currentCardGame(t, p)
				auditPlay(t, e, p, "乘胜追击")
				id := findCounterIDPerPlayer(e, "乘胜追击_count", p)
				if e.G.ReadCounter(id) != 0 {
					t.Fatal("activation counted")
				}
				for i := 1; i <= 3; i++ {
					auditPlay(t, e, p, "碌碌无为")
					if e.G.ReadCounter(id) != i {
						t.Fatalf("paid fast card count=%d want %d", e.G.ReadCounter(id), i)
					}
				}
				for i := 0; i < 3; i++ {
					e.G.GetLegalActions()
				}
				if e.G.ReadCounter(id) != 3 {
					t.Fatal("enumeration mutated count")
				}
				before := e.DiceTotal(p)
				switch kind {
				case "card":
					auditPlay(t, e, p, "乘胜追击")
				case "normal":
					auditSkill(t, e, p, "枪")
				case "elemental":
					auditSkill(t, e, p, "蝶火")
				case "same":
					auditPlay(t, e, p, "测试卡_增幅")
				case "switch":
					auditSwitch(t, e, p, 1)
				}
				want := 0
				if kind == "card" {
					want = 1
				}
				if spent := before - e.DiceTotal(p); spent != want {
					t.Fatalf("fourth spent=%d want %d", spent, want)
				}
				if e.G.ReadCounter(id) != 4 {
					t.Fatalf("fourth count=%d", e.G.ReadCounter(id))
				}
				before = e.DiceTotal(p)
				auditPlay(t, e, p, "碌碌无为")
				if before-e.DiceTotal(p) != 1 || e.G.ReadCounter(id) != 5 {
					t.Fatal("fifth operation must pay normally")
				}
				e.playToRoundEnd(t)
				e.G.GetLegalActions()
				if e.G.ReadCounter(id) != 0 {
					t.Fatal("round did not reset count")
				}
			})
		}
	}
}

func TestCurrentCards_YiYiOverhealCounts(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, hp := range []int{15, 14} {
			t.Run(fmt.Sprintf("P%d/hp%d", p, hp), func(t *testing.T) {
				e := currentCardGame(t, p)
				auditPlay(t, e, p, "以逸待劳")
				own := e.RT.Chars.BySlot[p][0]
				e.G.Counters[own.HPCounterID].Value = hp
				e.G.ExecuteEffect(engine.EventFrame{Player: p}, func(g *engine.Game) { g.Heal(own.HPCounterID, 3) })
				if e.HP(p, 0) != 15 || e.HP(1-p, 0) != 12 {
					t.Fatalf("own=%d enemy=%d; full requested heal must retaliate", e.HP(p, 0), e.HP(1-p, 0))
				}
			})
		}
	}
}
