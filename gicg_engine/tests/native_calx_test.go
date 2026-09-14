package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestNativeCalxTransfersFromEachDonorAndAllowsOverflow(t *testing.T) {
	for _, p := range []int{0, 1} {
		for active := 0; active < 3; active++ {
			for _, spec := range []struct {
				name                           string
				missing, first, second, gained int
			}{
				{"overflow", 1, 1, 1, 1}, {"two_donors", 2, 2, 2, 2},
				{"one_donor", 2, 2, 0, 1}, {"only_second", 2, 0, 1, 1},
				{"full", 0, 1, 1, 0}, {"empty_donors", 2, 0, 0, 0},
			} {
				t.Run(fmt.Sprintf("P%d_C%d_%s", p, active, spec.name), func(t *testing.T) {
					e := nativeTalentGame(t, "凯亚")
					e.G.ForceSwitchTo(p, active)
					first, second := (active+1)%3, (active+2)%3
					target := e.RT.Chars.BySlot[p][active].EnergyCounterID
					initial := e.G.Counters[target].Max - spec.missing
					e.G.WriteCounter(target, engine.OpSet, initial)
					e.G.WriteCounter(e.RT.Chars.BySlot[p][first].EnergyCounterID, engine.OpSet, spec.first)
					e.G.WriteCounter(e.RT.Chars.BySlot[p][second].EnergyCounterID, engine.OpSet, spec.second)
					e.G.Turn = p
					e.giveCard(t, p, "白垩之术")
					index := e.FindAction(engine.ActionCard, "白垩之术")
					if spec.gained == 0 {
						if index >= 0 {
							t.Fatal("calx playable with full receiver or no source energy")
						}
						return
					}
					if index < 0 {
						t.Fatal("legal energy transfer unavailable")
					}
					e.G.Step(index)
					if e.Energy(p, active) != initial+spec.gained || e.Energy(p, first) != max(0, spec.first-1) ||
						e.Energy(p, second) != max(0, spec.second-1) || e.DiceTotal(p) != 15 || e.G.Turn != p {
						t.Fatal("incorrect calx transfer, overflow, cost, or turn")
					}
					for c := 0; c < 3; c++ {
						if e.Energy(1-p, c) != 0 {
							t.Fatal("enemy energy changed")
						}
					}
				})
			}
		}
	}
}

func TestNativeCalxIgnoresDefeatedDonors(t *testing.T) {
	e := nativeTalentGame(t, "凯亚")
	nativeDamage(e, 0, 1, engine.ElemPiercing, 10)
	// Even a stale counter on a dead slot must not count as transferable energy.
	e.G.WriteCounter(e.RT.Chars.BySlot[0][1].EnergyCounterID, engine.OpSet, 1)
	e.G.Turn = 0
	e.giveCard(t, 0, "白垩之术")
	if e.FindAction(engine.ActionCard, "白垩之术") >= 0 {
		t.Fatal("dead donor unlocked calx")
	}
}
