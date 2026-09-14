package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestCurrentRules_ForcedSwitchPreservesCharges(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			for _, name := range []string{"伏兵之术", "瞬身之术", "乘胜追击", "碌碌无为", "碌碌无为", "碌碌无为"} {
				auditPlay(t, e, p, name)
			}
			e.G.Counters[e.RT.Chars.BySlot[p][0].HPCounterID].Value = 1
			e.SetDice(1-p, map[int]int{engine.DiceColorOmni: 4})
			e.G.Turn = 1 - p
			e.giveCard(t, 1-p, "测试卡_碎片")
			before := e.DiceTotal(p)
			if e.G.Step(e.FindAction(engine.ActionCard, "测试卡_碎片")) != engine.StepNeedTarget {
				t.Fatal("lethal card did not request replacement")
			}
			if e.Alive(p, 0) || e.HP(p, 0) != 0 {
				t.Fatal("victim not dead")
			}
			for i := 0; i < 3; i++ {
				acts := e.G.GetLegalActions()
				if len(acts) != 1 || !acts[0].Forced || acts[0].PlayerIdx != p || acts[0].Index != 1 {
					t.Fatal("replacement offers invalid actions")
				}
			}
			// Resume independent clones from the real card's input boundary.
			for i := 0; i < 2; i++ {
				rt := e.RT.Clone()
				branch := &GameEnv{G: rt.Game, RT: rt, T: t}
				branch.G.Step(0)
				if branch.G.PendingAction != nil || branch.G.Players[p].ActiveChar != 1 || branch.G.Turn != 1-p {
					t.Fatal("fast card continuation lost action ownership")
				}
				if branch.DiceTotal(p) != before {
					t.Fatal("forced switch spent dice")
				}
				for name, want := range map[string]int{"乘胜追击_count": 3, "伏兵之术_used": 0, "瞬身之术_used": 0} {
					if branch.G.ReadCounter(findCounterIDPerPlayer(branch, name, p)) != want {
						t.Fatalf("forced switch consumed %s", name)
					}
				}
			}
			if e.G.PendingAction == nil || e.G.Players[p].ActiveChar != 0 {
				t.Fatal("resuming clone mutated source")
			}
		})
	}
}

func TestCurrentRules_RoundEndDeathResumesRemainingSummon(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			e.SetDice(1-p, map[int]int{engine.DiceColorOmni: 8})
			auditPlay(t, e, p, "以牙还牙")
			auditPlay(t, e, 1-p, "以牙还牙")
			e.G.Counters[e.RT.Chars.BySlot[1-p][0].HPCounterID].Value = 1
			e.G.Turn = p
			e.G.Step(e.FindAction(engine.ActionEndTurn, ""))
			if e.G.Step(e.FindAction(engine.ActionEndTurn, "")) != engine.StepNeedTarget {
				t.Fatal("summon kill did not pause")
			}
			if e.HP(p, 0) != 15 || e.Alive(1-p, 0) {
				t.Fatal("remaining summon ran before replacement input")
			}
			for i := 0; i < 2; i++ {
				rt := e.RT.Clone()
				branch := &GameEnv{G: rt.Game, RT: rt, T: t}
				branch.G.Step(0)
				if branch.G.Phase != engine.PhaseRoundStart || branch.G.PendingAction != nil {
					t.Fatal("round end did not finish")
				}
				if branch.HP(p, 0) != 14 || branch.HP(1-p, 1) != 15 {
					t.Fatal("remaining summon duplicated, skipped or hit wrong target")
				}
				for side := 0; side < 2; side++ {
					if branch.G.ReadCounter(findCounterIDPerPlayer(branch, "以牙还牙_rounds", side)) != 1 {
						t.Fatal("summon duration did not decay exactly once")
					}
				}
			}
			if e.G.PendingAction == nil || e.HP(p, 0) != 15 {
				t.Fatal("clone changed waiting source")
			}
		})
	}
}

func TestCurrentRules_FirstEndWinsLethalSummonRace(t *testing.T) {
	for _, first := range []int{0, 1} {
		t.Run(fmt.Sprint(first), func(t *testing.T) {
			e := currentCardGame(t, first, []string{"赤蝶"}, []string{"墨客"})
			for p := 0; p < 2; p++ {
				e.SetDice(p, map[int]int{engine.DiceColorOmni: 8})
				auditPlay(t, e, p, "以牙还牙")
				e.G.Counters[e.RT.Chars.BySlot[p][0].HPCounterID].Value = 1
			}
			e.G.Turn = first
			e.G.Step(e.FindAction(engine.ActionEndTurn, ""))
			e.G.Step(e.FindAction(engine.ActionEndTurn, ""))
			if e.G.Phase != engine.PhaseGameOver || e.G.Winner != first || e.HP(first, 0) != 1 {
				t.Fatal("terminal round end ran the losing summon or used seat order")
			}
			if len(e.G.GetLegalActions()) != 0 {
				t.Fatal("terminal game still offers actions")
			}
		})
	}
}

func TestCurrentRules_SummonExpiresAfterTwoTicks(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "以牙还牙")
			for round := 1; round <= 3; round++ {
				e.playToRoundEnd(t)
				wantHP := 15 - min(round, 2)
				if e.HP(1-p, 0) != wantHP || e.G.ReadCounter(findCounterIDPerPlayer(e, "以牙还牙_rounds", p)) != max(2-round, 0) {
					t.Fatalf("wrong tick/decay at round %d", round)
				}
				e.G.GetLegalActions()
			}
		})
	}
}
