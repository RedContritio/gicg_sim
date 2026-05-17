package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// pool helper: build an 8-slot dice pool
func makePool(fire, ice, water, electro, geo, anemo, dendro, omni int) [engine.DiceColorCount]int {
	return [engine.DiceColorCount]int{fire, ice, water, electro, geo, anemo, dendro, omni}
}

// diceCost helper
func makeSpecific(color, n int) engine.DiceCost {
	c := engine.DiceCost{}
	c.Specific[color] = n
	return c
}

func TestCanAfford_PureSpecific(t *testing.T) {
	// 3 fire cost
	cost := makeSpecific(engine.DiceColorFire, 3)

	cases := []struct {
		pool [engine.DiceColorCount]int
		want bool
	}{
		{makePool(3, 0, 0, 0, 0, 0, 0, 0), true},  // exactly enough fire
		{makePool(2, 0, 0, 0, 0, 0, 0, 1), true},  // 2 fire + 1 omni
		{makePool(0, 0, 0, 0, 0, 0, 0, 3), true},  // 3 omni
		{makePool(2, 0, 0, 0, 0, 0, 0, 0), false}, // 2 fire, no omni
		{makePool(0, 5, 5, 0, 0, 0, 0, 2), false}, // lots of ice/water + 2 omni (still < 3 fire)
	}
	for i, c := range cases {
		if got := engine.CanAfford(c.pool, cost); got != c.want {
			t.Errorf("case %d pool=%v cost=3fire → %v, want %v", i, c.pool, got, c.want)
		}
	}
}

func TestCanAfford_SpecificPlusAny(t *testing.T) {
	// 1 fire + 2 any (normal attack)
	cost := engine.DiceCost{
		Specific: [7]int{1, 0, 0, 0, 0, 0, 0},
		Any:      2,
	}

	cases := []struct {
		pool [engine.DiceColorCount]int
		want bool
	}{
		{makePool(1, 1, 1, 0, 0, 0, 0, 0), true},  // 1 fire + 2 others
		{makePool(3, 0, 0, 0, 0, 0, 0, 0), true},  // 3 fire (1 fire + 2 as any)
		{makePool(0, 0, 0, 0, 0, 0, 0, 3), true},  // 3 omni
		{makePool(1, 0, 0, 0, 0, 0, 0, 0), false}, // only 1 fire
		{makePool(1, 1, 0, 0, 0, 0, 0, 0), false}, // 1 fire + 1 ice, short 1
	}
	for i, c := range cases {
		if got := engine.CanAfford(c.pool, cost); got != c.want {
			t.Errorf("case %d pool=%v → %v, want %v", i, c.pool, got, c.want)
		}
	}
}

func TestEnumerate_PureAnyN2(t *testing.T) {
	// 2 any, pool has 3 distinct colors
	pool := makePool(1, 1, 1, 0, 0, 0, 0, 0) // 1 fire + 1 ice + 1 water
	cost := engine.DiceCost{Any: 2}
	payments := engine.EnumerateCostPayments(pool, cost)
	// C(3, 2) = 3 unique multisets: {fire, ice}, {fire, water}, {ice, water}
	if len(payments) != 3 {
		t.Errorf("got %d payments, want 3: %v", len(payments), payments)
	}
}

func TestEnumerate_PureAnyWithMultiples(t *testing.T) {
	// 2 any from {2 fire, 1 ice} → {2 fire}, {1 fire + 1 ice} = 2 unique
	pool := makePool(2, 1, 0, 0, 0, 0, 0, 0)
	cost := engine.DiceCost{Any: 2}
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 2 {
		t.Errorf("got %d payments, want 2", len(payments))
	}
	// Verify each payment sums to 2
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

func TestEnumerate_SpecificPlusAny(t *testing.T) {
	// 1 fire + 2 any, pool: 3 fire + 1 ice + 1 omni
	pool := makePool(3, 1, 0, 0, 0, 0, 0, 1)
	cost := engine.DiceCost{
		Specific: [7]int{1, 0, 0, 0, 0, 0, 0},
		Any:      2,
	}
	payments := engine.EnumerateCostPayments(pool, cost)
	// Should produce several multisets. Each sums to 3.
	if len(payments) == 0 {
		t.Fatal("expected payments, got none")
	}
	for _, p := range payments {
		sum := 0
		for _, v := range p {
			sum += int(v)
		}
		if sum != 3 {
			t.Errorf("payment %v sums to %d, want 3", p, sum)
		}
	}
}

func TestEnumerate_Insufficient(t *testing.T) {
	// 5 fire required, only 2 fire + 1 omni available
	pool := makePool(2, 0, 0, 0, 0, 0, 0, 1)
	cost := makeSpecific(engine.DiceColorFire, 5)
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 0 {
		t.Errorf("got %d payments for unaffordable cost, want 0", len(payments))
	}
}

func TestEnumerate_PureSpecificOmniVariants(t *testing.T) {
	// 3 fire, pool: 3 fire + 2 omni
	// Omni can substitute 0..3 fires → {3 fire, 0 omni}, {2 fire, 1 omni},
	// {1 fire, 2 omni}, {0 fire, 3 omni}... but wait, 3 omni requires
	// 3 in pool and we only have 2. So valid: 0..2 omni.
	pool := makePool(3, 0, 0, 0, 0, 0, 0, 2)
	cost := makeSpecific(engine.DiceColorFire, 3)
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 3 {
		t.Errorf("got %d payments, want 3 (omni 0/1/2)", len(payments))
	}
}

func TestEnumerate_AllAny_HeavyPool(t *testing.T) {
	// 3 any from 5 distinct colors (1 each)
	pool := makePool(1, 1, 1, 1, 1, 0, 0, 0)
	cost := engine.DiceCost{Any: 3}
	payments := engine.EnumerateCostPayments(pool, cost)
	// C(5, 3) = 10 unique multisets
	if len(payments) != 10 {
		t.Errorf("got %d payments, want 10", len(payments))
	}
}

func TestEnumerate_EmptyCost(t *testing.T) {
	// 0-cost actions should produce a single "empty" payment
	pool := makePool(2, 0, 0, 0, 0, 0, 0, 0)
	cost := engine.DiceCost{}
	payments := engine.EnumerateCostPayments(pool, cost)
	if len(payments) != 1 {
		t.Errorf("got %d payments for empty cost, want 1 (the empty payment)", len(payments))
	}
	if payments[0] != ([engine.DiceColorCount]int8{}) {
		t.Errorf("empty cost should produce all-zero payment, got %v", payments[0])
	}
}

// Match-cost coverage lives in cost_match_test.go (same package,
// reuses makePool / makeSpecific helpers defined here).
