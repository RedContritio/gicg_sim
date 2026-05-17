package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestSetPlayerDice_OverwritesPool verifies that Runtime.SetPlayerDice
// replaces player 0's dice pool with the given per-color counts,
// leaves player 1's pool untouched, and that counts become visible
// via the DicePool read path (the same path the cost affordability
// checks use).
func TestSetPlayerDice_OverwritesPool(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	// Seed a known pool for P1 that we want to be undisturbed.
	env.SetDice(1, map[int]int{
		engine.DiceColorWater: 5,
	})
	p1Before := env.RT.DicePool(1)

	// Inject a deterministic pool for P0 via the new setter.
	var want [engine.DiceColorCount]int
	want[engine.DiceColorFire] = 3
	want[engine.DiceColorElectro] = 2
	want[engine.DiceColorOmni] = 1
	env.RT.SetPlayerDice(0, want)

	got := env.RT.DicePool(0)
	if got != want {
		t.Errorf("P0 dice pool = %v, want %v", got, want)
	}

	if env.RT.DicePool(1) != p1Before {
		t.Errorf("P1 dice pool disturbed: %v → %v",
			p1Before, env.RT.DicePool(1))
	}
}

// TestSetPlayerDice_EmptyCountsClears verifies that passing an all-zero
// counts vector clears the pool — the degenerate case when a
// determinized opponent has 0 dice.
func TestSetPlayerDice_EmptyCountsClears(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	env.SetDice(0, map[int]int{engine.DiceColorFire: 4})

	var zero [engine.DiceColorCount]int
	env.RT.SetPlayerDice(0, zero)

	total := 0
	pool := env.RT.DicePool(0)
	for _, v := range pool {
		total += v
	}
	if total != 0 {
		t.Errorf("expected empty pool after SetPlayerDice(zero), got total %d", total)
	}
}

// TestSetPlayerDice_InvalidPlayer verifies that out-of-range player
// indices panic.
func TestSetPlayerDice_InvalidPlayer(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	var counts [engine.DiceColorCount]int
	counts[engine.DiceColorFire] = 7
	for _, pi := range []int{-1, 2, 99} {
		func(p int) {
			defer func() {
				if r := recover(); r == nil {
					t.Errorf("SetPlayerDice(%d) did not panic", p)
				}
			}()
			env.RT.SetPlayerDice(p, counts)
		}(pi)
	}
}

// TestSetPlayerDice_NegativeCount verifies that a negative count for
// any color panics — the underlying counter is unsigned in spirit.
func TestSetPlayerDice_NegativeCount(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	var counts [engine.DiceColorCount]int
	counts[engine.DiceColorFire] = -1
	defer func() {
		if r := recover(); r == nil {
			t.Error("SetPlayerDice with negative count did not panic")
		}
	}()
	env.RT.SetPlayerDice(0, counts)
}

// TestDicePool_InvalidPlayerPanics — read-side probe still panics on
// a bad player index (that's a programmer bug regardless of whether
// the call is a read or a write).
func TestDicePool_InvalidPlayerPanics(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	defer func() {
		if r := recover(); r == nil {
			t.Error("DicePool(-1) did not panic")
		}
	}()
	_ = env.RT.DicePool(-1)
}

// TestGetDiceCount_InvalidColorPanics — bad color index panics.
func TestGetDiceCount_InvalidColorPanics(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	defer func() {
		if r := recover(); r == nil {
			t.Error("GetDiceCount(0, 99) did not panic")
		}
	}()
	_ = env.RT.GetDiceCount(0, 99)
}

// TestSetHiddenState_SnapshotIsolation verifies that setting hidden
// state on a clone does not leak back to the original. This is the
// canonical use pattern for IS-MCTS determinization: snapshot the root,
// clone/restore, inject determinized hidden state, roll forward, then
// restore the root for the next rollout — the original must not be
// polluted.
func TestSetHiddenState_SnapshotIsolation(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// Capture original P0 hand
	origHandSize := len(g.Players[0].Hand)
	origHandCopy := make([]engine.CardInst, origHandSize)
	copy(origHandCopy, g.Players[0].Hand)

	// Take a snapshot
	snap := g.DeepCopy()

	// Mutate the snapshot's hand
	fillerCard := env.RT.Cards.ByName["碌碌无为"]
	if fillerCard == nil {
		t.Fatal("filler card not found")
	}
	snap.SetPlayerHand(0, []int{fillerCard.Ref, fillerCard.Ref})

	// Original is untouched
	if len(g.Players[0].Hand) != origHandSize {
		t.Errorf("original hand size changed from %d to %d",
			origHandSize, len(g.Players[0].Hand))
	}
	for i, card := range g.Players[0].Hand {
		if card.Ref != origHandCopy[i].Ref {
			t.Errorf("original hand[%d] mutated: ref %d → %d",
				i, origHandCopy[i].Ref, card.Ref)
		}
	}

	// Snapshot has the injected hand
	if len(snap.Players[0].Hand) != 2 {
		t.Errorf("snapshot hand size = %d, want 2",
			len(snap.Players[0].Hand))
	}
}
