package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// Match-cost coverage. The fixture helpers (makePool, makeSpecific)
// live in cost_payment_test.go; this file only adds Match-specific
// cases so the parent file stays under the 300-line pre-commit cap.

func TestCanAfford_PureMatch(t *testing.T) {
	// Match=2: need 2 dice of same color (omni substitutes).
	cost := engine.DiceCost{Match: 2}
	cases := []struct {
		label string
		pool  [engine.DiceColorCount]int
		want  bool
	}{
		{"2 fire", makePool(2, 0, 0, 0, 0, 0, 0, 0), true},
		{"5 electro", makePool(0, 0, 0, 5, 0, 0, 0, 0), true},
		{"1 fire + 1 omni (same-color via sub)", makePool(1, 0, 0, 0, 0, 0, 0, 1), true},
		{"0 native + 2 omni (all-omni payment)", makePool(0, 0, 0, 0, 0, 0, 0, 2), true},
		{"all distinct singletons, no omni", makePool(1, 1, 1, 1, 1, 1, 1, 0), false},
		{"all distinct singletons + 1 omni (1 native + 1 omni of any color)", makePool(1, 1, 1, 0, 0, 0, 0, 1), true},
		{"empty", makePool(0, 0, 0, 0, 0, 0, 0, 0), false},
	}
	for _, c := range cases {
		if got := engine.CanAfford(c.pool, cost); got != c.want {
			t.Errorf("%s: CanAfford=%v, want %v", c.label, got, c.want)
		}
	}
}

func TestCanAfford_SpecificPlusMatch(t *testing.T) {
	// Specific[fire]=2, Match=2. Specific consumes fire natively; match
	// must find a different color (or fire again if surplus).
	cost := engine.DiceCost{Specific: [7]int{2, 0, 0, 0, 0, 0, 0}, Match: 2}
	cases := []struct {
		label string
		pool  [engine.DiceColorCount]int
		want  bool
	}{
		{"2 fire + 2 ice", makePool(2, 2, 0, 0, 0, 0, 0, 0), true},
		{"2 fire + 1 ice (can't form match=2)", makePool(2, 1, 0, 0, 0, 0, 0, 0), false},
		{"2 fire + 1 ice + 1 omni (1 ice + 1 omni for match)", makePool(2, 1, 0, 0, 0, 0, 0, 1), true},
		{"4 fire (2 fire for spec, 2 fire for match=fire)", makePool(4, 0, 0, 0, 0, 0, 0, 0), true},
		{"2 fire only (can't pay match at all)", makePool(2, 0, 0, 0, 0, 0, 0, 0), false},
		{"0 fire + 4 omni (2 omni for spec, 2 omni for match)", makePool(0, 0, 0, 0, 0, 0, 0, 4), true},
	}
	for _, c := range cases {
		if got := engine.CanAfford(c.pool, cost); got != c.want {
			t.Errorf("%s: CanAfford=%v, want %v", c.label, got, c.want)
		}
	}
}

func TestCanAfford_MatchPlusAny(t *testing.T) {
	// Match=2 + Any=1. Total 3 dice.
	cost := engine.DiceCost{Match: 2, Any: 1}
	cases := []struct {
		label string
		pool  [engine.DiceColorCount]int
		want  bool
	}{
		{"2 fire + 1 ice", makePool(2, 1, 0, 0, 0, 0, 0, 0), true},
		{"2 fire only (no dice for any)", makePool(2, 0, 0, 0, 0, 0, 0, 0), false},
		{"3 ice (2 for match, 1 for any)", makePool(0, 3, 0, 0, 0, 0, 0, 0), true},
	}
	for _, c := range cases {
		if got := engine.CanAfford(c.pool, cost); got != c.want {
			t.Errorf("%s: CanAfford=%v, want %v", c.label, got, c.want)
		}
	}
}

func TestEnumerate_PureMatch(t *testing.T) {
	// Match=2 from pool with 2 fire + 3 electro.
	// Expected multisets: {2 fire}, {2 electro} — one per color with
	// ≥2 native. (No omni in pool, no substitution variants.)
	pool := makePool(2, 0, 0, 3, 0, 0, 0, 0)
	cost := engine.DiceCost{Match: 2}
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 2 {
		t.Errorf("got %d payments, want 2 ({2 fire}, {2 electro}): %v", len(payments), payments)
	}
	for _, p := range payments {
		sum := 0
		for _, v := range p {
			sum += int(v)
		}
		if sum != 2 {
			t.Errorf("payment %v sums to %d, want 2", p, sum)
		}
	}
}

func TestEnumerate_MatchWithOmniSub(t *testing.T) {
	// Match=2 from 1 fire + 2 omni. Pool has native fire=1, so (2F+0O)
	// is NOT payable (need 2 native fires but only 1 exists). Variants:
	//   under c=fire: (1F+1O), (0F+2O)  — 2 variants, dedup {1F+1O} and {2O}
	//   under c=ice..dendro: (0+2O)     — all identical multiset {2O}
	// After cross-color dedup: {1F+1O}, {2O} = 2 unique multisets.
	pool := makePool(1, 0, 0, 0, 0, 0, 0, 2)
	cost := engine.DiceCost{Match: 2}
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 2 {
		t.Errorf("got %d payments, want 2 ({1F+1O},{2O}): %v", len(payments), payments)
	}
	seen := map[[engine.DiceColorCount]int8]int{}
	for _, p := range payments {
		seen[p]++
	}
	for p, n := range seen {
		if n > 1 {
			t.Errorf("duplicate multiset %v appears %d times", p, n)
		}
	}
}

func TestEnumerate_MatchWithEnoughNative(t *testing.T) {
	// 2 fire + 2 omni. Match=2. Fire-color variants:
	//   (2F+0O), (1F+1O), (0F+2O)  — 3 distinct multisets
	// Ice..dendro: (0+2O) = dup of fire's (0F+2O).
	// Final: 3 unique multisets.
	pool := makePool(2, 0, 0, 0, 0, 0, 0, 2)
	cost := engine.DiceCost{Match: 2}
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 3 {
		t.Errorf("got %d payments, want 3 ({2F},{1F+1O},{2O}): %v", len(payments), payments)
	}
}

func TestEnumerate_MatchAllOmniDeduped(t *testing.T) {
	// Pure-omni pool: Match=2 from 0 native + 2 omni. Only {2 omni}
	// is a valid multiset, but enumeration visits it once per color
	// choice (7 times). After dedup, exactly 1 payment.
	pool := makePool(0, 0, 0, 0, 0, 0, 0, 2)
	cost := engine.DiceCost{Match: 2}
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 1 {
		t.Errorf("got %d payments, want 1 ({2 omni} dedup): %v", len(payments), payments)
	}
	want := [engine.DiceColorCount]int8{0, 0, 0, 0, 0, 0, 0, 2}
	if payments[0] != want {
		t.Errorf("got %v, want %v", payments[0], want)
	}
}

func TestEnumerate_SpecificPlusMatch(t *testing.T) {
	// Specific[fire]=2, Match=2. Pool: 2 fire + 2 ice.
	// Specific must use 2 fire (no omni to sub).
	// Match must use 2 ice (the only remaining same-color pair).
	// Expected: 1 multiset = {2 fire + 2 ice}.
	pool := makePool(2, 2, 0, 0, 0, 0, 0, 0)
	cost := engine.DiceCost{Specific: [7]int{2, 0, 0, 0, 0, 0, 0}, Match: 2}
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 1 {
		t.Errorf("got %d, want 1: %v", len(payments), payments)
	}
	want := [engine.DiceColorCount]int8{2, 2, 0, 0, 0, 0, 0, 0}
	if payments[0] != want {
		t.Errorf("got %v, want %v", payments[0], want)
	}
}

func TestEnumerate_MatchInsufficient(t *testing.T) {
	// Match=3 from 1 fire + 1 ice + 1 water — no color has 3, no omni.
	pool := makePool(1, 1, 1, 0, 0, 0, 0, 0)
	cost := engine.DiceCost{Match: 3}
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 0 {
		t.Errorf("got %d, want 0 (infeasible): %v", len(payments), payments)
	}
}
