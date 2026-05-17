package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestDiceCost_ModSpecific verifies Mod applies delta to individual
// specific slots.
func TestDiceCost_ModSpecific(t *testing.T) {
	c := engine.DiceCost{}
	c.Mod(engine.CostFire, 3)
	if c.Specific[engine.CostFire] != 3 {
		t.Errorf("Specific[Fire] = %d, want 3", c.Specific[engine.CostFire])
	}
	c.Mod(engine.CostFire, -1)
	if c.Specific[engine.CostFire] != 2 {
		t.Errorf("Specific[Fire] = %d, want 2", c.Specific[engine.CostFire])
	}
}

// TestDiceCost_ModAny verifies Mod applies delta to the Any slot.
func TestDiceCost_ModAny(t *testing.T) {
	c := engine.DiceCost{Any: 2}
	c.Mod(engine.CostAny, -1)
	if c.Any != 1 {
		t.Errorf("Any = %d, want 1", c.Any)
	}
}

// TestDiceCost_ModMatch verifies Mod applies delta to the Match slot.
func TestDiceCost_ModMatch(t *testing.T) {
	c := engine.DiceCost{}
	c.Mod(engine.CostMatch, 2)
	if c.Match != 2 {
		t.Errorf("Match = %d, want 2", c.Match)
	}
}

// TestDiceCost_ModAllSentinel verifies CostAll adds delta to every
// real slot (7 specific + match + any).
func TestDiceCost_ModAllSentinel(t *testing.T) {
	c := engine.DiceCost{
		Specific: [7]int{1, 0, 0, 0, 0, 0, 0},
		Any:      2,
	}
	c.Mod(engine.CostAll, -99)
	// Every slot should be decremented by 99
	if c.Specific[0] != 1-99 {
		t.Errorf("Specific[0] = %d, want %d", c.Specific[0], 1-99)
	}
	if c.Specific[1] != -99 {
		t.Errorf("Specific[1] = %d, want -99", c.Specific[1])
	}
	if c.Any != 2-99 {
		t.Errorf("Any = %d, want %d", c.Any, 2-99)
	}
	if c.Match != -99 {
		t.Errorf("Match = %d, want -99", c.Match)
	}
}

// TestDiceCost_Clamp verifies Clamp sets negative slots to 0.
func TestDiceCost_Clamp(t *testing.T) {
	c := engine.DiceCost{
		Specific: [7]int{-5, 3, 0, -1, 2, 0, 0},
		Match:    -2,
		Any:      -10,
	}
	c.Clamp()
	want := engine.DiceCost{
		Specific: [7]int{0, 3, 0, 0, 2, 0, 0},
		Match:    0,
		Any:      0,
	}
	if c != want {
		t.Errorf("Clamp() = %+v, want %+v", c, want)
	}
}

// TestDiceCost_ClampAfterAllZero verifies clamp+all-sentinel idiom
// produces a fully zero cost (the "free action" pattern).
func TestDiceCost_ClampAfterAllZero(t *testing.T) {
	c := engine.DiceCost{
		Specific: [7]int{3, 0, 0, 0, 0, 0, 0},
		Any:      2,
	}
	c.Mod(engine.CostAll, -99)
	c.Clamp()
	if !c.IsEmpty() {
		t.Errorf("expected IsEmpty after All -99 + Clamp, got %+v", c)
	}
}

// TestDiceCost_ClampedTotal verifies the read helper used by the
// cost_total DSL builtin treats negative slots as zero.
func TestDiceCost_ClampedTotal(t *testing.T) {
	c := engine.DiceCost{
		Specific: [7]int{-5, 3, 0, 0, 0, 0, 0},
		Any:      2,
	}
	// Raw Total = -5 + 3 + 2 = 0, but clamped Total ignores negatives.
	if got := c.ClampedTotal(); got != 5 {
		t.Errorf("ClampedTotal = %d, want 5 (3 + 2)", got)
	}
}

// TestDiceCost_TotalIncludesAllSlots verifies Total sums every slot
// without clamping (to catch callers who forgot to Clamp before
// calling EnumerateCostPayments).
func TestDiceCost_TotalIncludesAllSlots(t *testing.T) {
	c := engine.DiceCost{
		Specific: [7]int{1, 2, 0, 0, 0, 0, 0},
		Match:    1,
		Any:      2,
	}
	if got := c.Total(); got != 6 {
		t.Errorf("Total = %d, want 6", got)
	}
}

// Match cost is now implemented — canonical behavior is covered by
// the suite in cost_payment_test.go::Test{CanAfford,Enumerate}_*Match*.
// The previous "expect panic" tests were removed when Match support
// landed (see dice_scheduling probe work).
