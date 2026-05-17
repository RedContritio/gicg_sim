package enginev2

import "testing"

// A24 — cost auto-resolve simple
func TestA24AutoResolveSimple(t *testing.T) {
	cost := CostSpec{}
	cost.Specific[DiceFire] = 1
	cost.Any = 2

	pool := DicePool{}
	pool[DiceFire] = 3
	pool[DiceElectro] = 3 // Omni=0

	consumed, needsSubstate, ok := CostPaymentDecision(cost, pool)
	if !ok {
		t.Fatalf("expected ok")
	}
	if needsSubstate {
		t.Errorf("expected auto-resolve, got substate=true")
	}
	if consumed[DiceFire] != 3 {
		t.Errorf("expected 火=3 (字典序最小), got %d", consumed[DiceFire])
	}
	if consumed[DiceElectro] != 0 {
		t.Errorf("expected 雷=0, got %d", consumed[DiceElectro])
	}
}

// A24 meaningful: same cost + 多种 specific 满足 → enter substate
func TestA24MeaningfulSameCost(t *testing.T) {
	cost := CostSpec{Same: 2}
	pool := DicePool{}
	pool[DiceFire] = 2
	pool[DiceElectro] = 2
	pool[DiceWater] = 1

	_, needsSubstate, _ := CostPaymentDecision(cost, pool)
	if !needsSubstate {
		t.Errorf("expected meaningful (火/雷 都满足 same=2), got auto")
	}
}

// A24 perf O(N) 不是 NP
func TestA24PerfNotNP(t *testing.T) {
	cost := CostSpec{Same: 3, Any: 2}
	cost.Specific[DiceFire] = 1
	cost.Specific[DiceWater] = 2

	pool := DicePool{}
	for c := DiceFire; c < DiceColorCount; c++ {
		pool[c] = 8
	}

	for i := 0; i < 100000; i++ {
		_, _, ok := CostPaymentDecision(cost, pool)
		if !ok {
			t.Fatalf("iter %d: expected ok", i)
		}
	}
}

// A24 cost insufficient
func TestA24Insufficient(t *testing.T) {
	cost := CostSpec{}
	cost.Specific[DiceFire] = 5
	pool := DicePool{}
	pool[DiceFire] = 2

	_, _, ok := CostPaymentDecision(cost, pool)
	if ok {
		t.Errorf("expected ok=false (火 needed 5 but pool 2)")
	}
}
