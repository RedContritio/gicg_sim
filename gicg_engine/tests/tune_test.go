package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestExecuteTune_ConvertsDiceAndDiscardsCard verifies that a tune
// action:
//  1. consumes one hand card (moves to discard)
//  2. decrements one dice of the source color
//  3. increments one dice of the active char's element color
func TestExecuteTune_ConvertsDiceAndDiscardsCard(t *testing.T) {
	// 赤蝶 (Fire) vs 墨客 (Water)
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	g.Players[0].ActiveChar = 0

	// Controlled pool: 1 ice (source), 2 water, 0 fire.
	env.SetDice(0, map[int]int{
		engine.DiceColorIce:   1,
		engine.DiceColorWater: 2,
	})
	iceID := env.RT.DiceCounterID(0, engine.DiceColorIce)
	waterID := env.RT.DiceCounterID(0, engine.DiceColorWater)
	fireID := env.RT.DiceCounterID(0, engine.DiceColorFire)

	if len(g.Players[0].Hand) == 0 {
		t.Fatal("expected non-empty P0 hand after NewGameWithDeck")
	}
	handBefore := len(g.Players[0].Hand)
	discardBefore := len(g.Players[0].Discard)

	// Find the tune action: source=ice (赤蝶 is fire, so ice is non-native)
	// on hand index 0.
	actions := g.GetLegalActions()
	tuneIdx := -1
	for i, a := range actions {
		if a.Kind == engine.ActionTune && a.Index == 0 && a.TuneSourceColor == engine.DiceColorIce {
			tuneIdx = i
			break
		}
	}
	if tuneIdx < 0 {
		t.Fatalf("no tune action found (legal actions: %d)", len(actions))
	}

	env.Step(tuneIdx)

	if len(g.Players[0].Hand) != handBefore-1 {
		t.Errorf("hand size %d, want %d", len(g.Players[0].Hand), handBefore-1)
	}
	if len(g.Players[0].Discard) != discardBefore+1 {
		t.Errorf("discard size %d, want %d", len(g.Players[0].Discard), discardBefore+1)
	}
	if g.Counters[iceID].Value != 0 {
		t.Errorf("ice dice %d, want 0", g.Counters[iceID].Value)
	}
	if g.Counters[fireID].Value != 1 {
		t.Errorf("fire dice %d, want 1", g.Counters[fireID].Value)
	}
	if g.Counters[waterID].Value != 2 {
		t.Errorf("water dice %d, want 2 (unchanged)", g.Counters[waterID].Value)
	}
}

// TestPayDice_DecrementsPool verifies that PayDice decrements the
// per-color dice counters by the payment's amounts.
func TestPayDice_DecrementsPool(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// Controlled pool: 3 fire, 2 omni
	env.RT.ClearDice(0)
	fireID := env.RT.DiceCounterID(0, engine.DiceColorFire)
	omniID := env.RT.DiceCounterID(0, engine.DiceColorOmni)
	g.Counters[fireID].Value = 3
	g.Counters[omniID].Value = 2

	// Pay 2 fire + 1 omni
	payment := [engine.DiceColorCount]int8{}
	payment[engine.DiceColorFire] = 2
	payment[engine.DiceColorOmni] = 1
	g.PayDice(0, payment)

	if g.Counters[fireID].Value != 1 {
		t.Errorf("fire = %d, want 1", g.Counters[fireID].Value)
	}
	if g.Counters[omniID].Value != 1 {
		t.Errorf("omni = %d, want 1", g.Counters[omniID].Value)
	}
}
