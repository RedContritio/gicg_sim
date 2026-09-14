package tests

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestRoundSummonFirstEndDecidesLethal(t *testing.T) {
	for _, first := range []int{0, 1} {
		e := currentCardGame(t, 0, []string{"赤蝶"}, []string{"赤蝶"})
		for _, p := range []int{0, 1} {
			e.G.WriteCounter(e.RT.Chars.BySlot[p][0].HPCounterID, engine.OpSet, 1)
			e.G.WriteCounter(findCounterIDPerPlayer(e, "以牙还牙_rounds", p), engine.OpSet, 2)
			e.G.WriteCounter(findCounterIDPerPlayer(e, "以牙还牙_elem", p), engine.OpSet, int(engine.ElemPhysical))
		}
		e.G.FirstEnd = first
		e.G.EndPhase()
		if e.G.Winner != first {
			t.Fatalf("first=%d winner=%d", first, e.G.Winner)
		}
	}
}

func TestRoundMarksGlobalCreationDecidesLethal(t *testing.T) {
	for _, first := range []int{0, 1} {
		e := currentCardGame(t, 0, []string{"赤蝶"}, []string{"赤蝶"})
		for _, p := range []int{1, 0} {
			e.G.WriteCounter(e.RT.Chars.BySlot[p][0].HPCounterID, engine.OpSet, 1)
			entry := e.RT.Counters.Entries["蝶印"]
			for _, id := range entry.CounterIDs {
				if e.G.GetCounterChar(id) == [2]int{p, 0} {
					e.G.WriteCounter(id, engine.OpSet, 1)
				}
			}
		}
		e.G.FirstEnd = first
		e.G.EndPhase()
		if e.G.Winner != 0 {
			t.Fatalf("first=%d changed global mark order, winner=%d", first, e.G.Winner)
		}
	}
}
