package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestDiceIndexBuiltAfterLoad verifies BuildDiceIndex resolves all 8
// canonical dice counter names into concrete counter IDs after the
// DSL load completes.
func TestDiceIndexBuiltAfterLoad(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	env.RT.Ruleset.BuildDiceIndex()

	for pi := 0; pi < 2; pi++ {
		for color := 0; color < engine.DiceColorCount; color++ {
			cid := env.RT.Ruleset.DiceCounterIDs[pi][color]
			if cid < 0 {
				t.Errorf("dice index [%d][%d] = -1, expected valid counter id",
					pi, color)
			}
		}
	}
}

// TestRollDiceProducesCorrectTotal verifies n rolls produce exactly n
// total dice in the player's pool. We clear both players first to
// isolate from the round_start roll triggered by NewGameWithDeck.
func TestRollDiceProducesCorrectTotal(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	env.RT.ClearDice(0)
	env.RT.ClearDice(1)

	env.RT.RollDice(0, 8)
	pool := env.RT.DicePool(0)

	total := 0
	for _, v := range pool {
		total += v
	}
	if total != 8 {
		t.Errorf("after RollDice(0, 8), total = %d, want 8", total)
	}

	// P1 should be untouched by rolling P0
	p1Pool := env.RT.DicePool(1)
	p1Total := 0
	for _, v := range p1Pool {
		p1Total += v
	}
	if p1Total != 0 {
		t.Errorf("P1 pool total = %d after rolling P0, want 0", p1Total)
	}
}

// TestNewGameAutoRollsDice verifies that the round_start hook fires
// roll_dice for both players automatically, so a fresh game has 8
// dice per player without explicit RollDice calls.
func TestNewGameAutoRollsDice(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	for pi := 0; pi < 2; pi++ {
		pool := env.RT.DicePool(pi)
		total := 0
		for _, v := range pool {
			total += v
		}
		if total != 8 {
			t.Errorf("P%d auto-rolled dice total = %d, want 8", pi, total)
		}
	}
}

// TestRollDiceClearsPreviousPool verifies RollDice zeroes existing
// dice before rolling new ones (so calling it twice doesn't accumulate
// to 16 dice from two 8-rolls).
func TestRollDiceClearsPreviousPool(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	env.RT.RollDice(0, 8)
	env.RT.RollDice(0, 8) // second call should replace, not add

	pool := env.RT.DicePool(0)
	total := 0
	for _, v := range pool {
		total += v
	}
	if total != 8 {
		t.Errorf("after two RollDice(0, 8) calls, total = %d, want 8 (second roll must replace first)", total)
	}
}

// TestClearDice zeroes the target player's pool.
func TestClearDice(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	env.RT.RollDice(0, 8)
	env.RT.RollDice(1, 8)

	env.RT.ClearDice(0)

	pool0 := env.RT.DicePool(0)
	for color, v := range pool0 {
		if v != 0 {
			t.Errorf("P0 pool[%d] = %d after ClearDice, want 0", color, v)
		}
	}

	pool1 := env.RT.DicePool(1)
	total1 := 0
	for _, v := range pool1 {
		total1 += v
	}
	if total1 != 8 {
		t.Errorf("P1 pool total = %d after clearing P0, want 8 (unchanged)", total1)
	}
}

// TestRollDiceDistributionRoughly: rolling many times should touch
// every color at least once (probability of NOT rolling a color over
// 1000 rolls × 8 dice each = (7/8)^8000, vanishingly small).
func TestRollDiceDistributionRoughly(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	counts := [engine.DiceColorCount]int{}
	for i := 0; i < 1000; i++ {
		env.RT.RollDice(0, 8)
		pool := env.RT.DicePool(0)
		for color, v := range pool {
			counts[color] += v
		}
	}

	// Expected: 1000 rolls × 8 dice × 1/8 = 1000 per color
	// Allow wide tolerance (±30% of 1000 = 700..1300)
	for color, count := range counts {
		if count < 700 || count > 1300 {
			t.Errorf("color %d: count = %d (expected ~1000 ± 300)", color, count)
		}
	}
}

// TestGetDiceCount returns the correct per-color count.
func TestGetDiceCount(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	env.RT.RollDice(0, 8)
	total := 0
	for color := 0; color < engine.DiceColorCount; color++ {
		total += env.RT.GetDiceCount(0, color)
	}
	if total != 8 {
		t.Errorf("sum of GetDiceCount = %d, want 8", total)
	}
}

// TestRollDicePreservedAcrossSnapshot verifies that dice counters are
// included in the game snapshot (they're regular counters). A snapshot
// taken after a roll should, on restore, contain the same dice values.
func TestRollDicePreservedAcrossSnapshot(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	env.RT.RollDice(0, 8)
	before := env.RT.DicePool(0)

	snap := env.G.DeepCopy()

	// Mutate the original: clear P0 dice
	env.RT.ClearDice(0)
	after := env.RT.DicePool(0)
	total := 0
	for _, v := range after {
		total += v
	}
	if total != 0 {
		t.Fatalf("ClearDice didn't clear pool (total = %d)", total)
	}

	// The snap should still have the original dice
	for color := 0; color < engine.DiceColorCount; color++ {
		cid := env.RT.Ruleset.DiceCounterIDs[0][color]
		if cid < 0 {
			continue
		}
		snapVal := snap.Counters[cid].Value
		if snapVal != before[color] {
			t.Errorf("snap dice[%d] = %d, want %d (snapshot lost dice state)",
				color, snapVal, before[color])
		}
	}
}
