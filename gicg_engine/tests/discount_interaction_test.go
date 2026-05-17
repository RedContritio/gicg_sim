package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// countHandCard returns the number of cards in player p's hand with
// the given name.
func (env *GameEnv) countHandCard(p int, name string) int {
	n := 0
	for _, c := range env.G.Players[p].Hand {
		if env.G.CardNames[c.Ref] == name {
			n++
		}
	}
	return n
}

// setBuffToOne gives the test buff pattern for 速速茶点 (one stack on
// P0's active char) without going through playCard.
func (env *GameEnv) setBuffToOne(t *testing.T, name string, p, c int) {
	t.Helper()
	for id, cname := range env.G.CounterNames {
		if cname != name {
			continue
		}
		m := env.G.GetCounterChar(id)
		if m[0] == p && m[1] == c {
			env.G.Counters[id].Value = 1
			return
		}
	}
	t.Fatalf("counter %q not found for P%d C%d", name, p, c)
}

// setCounterGlobal sets the first counter with the given name
// regardless of scope. Handles PerPlayer counters for test setup.
func (env *GameEnv) setCounterPerPlayer(t *testing.T, name string, p, value int) {
	t.Helper()
	for id, cname := range env.G.CounterNames {
		if cname != name {
			continue
		}
		m := env.G.GetCounterChar(id)
		if m[0] == p && m[1] == -1 {
			env.G.Counters[id].Value = value
			return
		}
	}
	t.Fatalf("PerPlayer counter %q not found for P%d", name, p)
}

// TestDiscount_速速茶点_Alone verifies that with ONLY the 速速茶点
// buff active (no other discount sources), using a normal attack
// applies the -1 any discount and consumes one buff stack.
func TestDiscount_速速茶点_Alone(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	// Activate 速速茶点 buff on P0's 赤蝶 (c0). Skip the play-card
	// path; we just need buff > 0.
	env.setBuffToOne(t, "速速茶点_buff", 0, 0)
	buffBefore := env.counterByChar("速速茶点_buff", 0, 0)
	if buffBefore != 1 {
		t.Fatalf("buff setup failed: %d", buffBefore)
	}

	// Stock enough fire dice for 枪 (1 fire + 2 any).
	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 8})

	// Play 枪 (P0's first skill = normal attack)
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available")
	}

	buffAfter := env.counterByChar("速速茶点_buff", 0, 0)
	if buffAfter != 0 {
		t.Errorf("buff after normal attack = %d, want 0 (consumed)", buffAfter)
	}

	// Dice spent should be 2 (1 fire + 1 any, discounted from 3).
	// Starting pool was 8 fire. After 枪, should have 6 fire left.
	remaining := env.DiceTotal(0)
	if remaining != 6 {
		t.Errorf("dice remaining = %d, want 6 (spent 2 due to -1 discount)", remaining)
	}
}

// TestDiscount_速速茶点_NotConsumedOnOtherSkill verifies buff stays
// when player uses a non-normal-attack skill (shouldn't apply).
func TestDiscount_速速茶点_NotConsumedOnOtherSkill(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	env.setBuffToOne(t, "速速茶点_buff", 0, 0)
	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 8})

	// Play 蝶火 (elemental skill, not the first/normal attack)
	if !env.StepSkill("蝶火") {
		t.Fatal("蝶火 not available")
	}

	buffAfter := env.counterByChar("速速茶点_buff", 0, 0)
	if buffAfter != 1 {
		t.Errorf("buff after non-normal attack = %d, want 1 (unchanged)", buffAfter)
	}
}

// TestDiscount_反制_Alone verifies that 反制 debuff adds 1 any cost
// to the target's next skill and consumes on trigger.
func TestDiscount_反制_Alone(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	// Place 反制 debuff on P0's 赤蝶
	env.setBuffToOne(t, "反制_debuff", 0, 0)

	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 8})

	// Play 枪 (cost 1 fire + 2 any = 3 normally, but 反制 makes it 4).
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available")
	}

	debuffAfter := env.counterByChar("反制_debuff", 0, 0)
	if debuffAfter != 0 {
		t.Errorf("debuff after triggered skill = %d, want 0 (consumed)", debuffAfter)
	}

	remaining := env.DiceTotal(0)
	// Paid 4 dice (1 fire + 3 any from the fire pool) → 4 remaining from 8
	if remaining != 4 {
		t.Errorf("dice remaining = %d, want 4 (spent 4 due to +1 penalty)", remaining)
	}
}

// TestDiscount_乘胜追击_4thActionFree verifies the 4th battle action
// of the round is free under 乘胜追击. Uses the fact that cost_mod
// All -99 zeros every slot after clamp.
func TestDiscount_乘胜追击_4thActionFree(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	// Activate 乘胜追击 on P0
	env.setCounterPerPlayer(t, "乘胜追击_active", 0, 1)
	// Pretend 3 battle actions already happened this round
	env.setCounterPerPlayer(t, "乘胜追击_count", 0, 3)

	env.PlayUntilTurn(0, 10)
	poolBefore := env.DiceTotal(0)

	// Play 枪 — should be free under 乘胜追击 4th-action bonus.
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available")
	}

	poolAfter := env.DiceTotal(0)
	if poolAfter != poolBefore {
		t.Errorf("dice pool changed by %d; want 0 (4th action is free)",
			poolBefore-poolAfter)
	}
}

// TestDiscount_速速茶点_NotWasted_When_乘胜追击_Frees verifies the
// key requirement: when 乘胜追击 makes an action free, 速速茶点's
// buff is NOT consumed (waste prevention).
func TestDiscount_速速茶点_NotWasted_When_乘胜追击_Frees(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	// Both buffs active
	env.setBuffToOne(t, "速速茶点_buff", 0, 0)
	env.setCounterPerPlayer(t, "乘胜追击_active", 0, 1)
	env.setCounterPerPlayer(t, "乘胜追击_count", 0, 3) // next action = 4th

	env.PlayUntilTurn(0, 10)
	poolBefore := env.DiceTotal(0)

	// Play 枪 — 乘胜追击 zeros cost; 速速茶点 should short-circuit
	// (cost_total == 0 gate) and NOT consume its buff.
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available")
	}

	// Free action: pool unchanged
	poolAfter := env.DiceTotal(0)
	if poolAfter != poolBefore {
		t.Errorf("dice pool changed by %d; want 0 (4th action is free)",
			poolBefore-poolAfter)
	}

	// 速速茶点 buff should be preserved (not wasted on already-free
	// action)
	buffAfter := env.counterByChar("速速茶点_buff", 0, 0)
	if buffAfter != 1 {
		t.Errorf("速速茶点_buff after free action = %d, want 1 (not consumed)",
			buffAfter)
	}
}

// TestDiscount_伏兵之术_NotWasted_When_乘胜追击_Frees verifies the
// other direction: when switching and 乘胜追击 would make the switch
// free anyway, 伏兵之术's used flag should NOT flip.
func TestDiscount_伏兵之术_NotWasted_When_乘胜追击_Frees(t *testing.T) {
	env := NewGame(t, []string{"赤蝶", "墨客"}, []string{"墨客"})

	// Activate 伏兵之术 on P0
	env.setCounterPerPlayer(t, "伏兵之术_active", 0, 1)
	// Activate 乘胜追击 4th action
	env.setCounterPerPlayer(t, "乘胜追击_active", 0, 1)
	env.setCounterPerPlayer(t, "乘胜追击_count", 0, 3)

	env.PlayUntilTurn(0, 10)
	poolBefore := env.DiceTotal(0)

	// Switch to 墨客 (char index 1)
	actions := env.G.GetLegalActions()
	switchIdx := -1
	for i, a := range actions {
		if a.Kind == engine.ActionSwitch && a.Index == 1 {
			switchIdx = i
			break
		}
	}
	if switchIdx < 0 {
		t.Fatal("switch to 墨客 not available")
	}
	env.Step(switchIdx)

	// Pool unchanged (free from 乘胜追击)
	if env.DiceTotal(0) != poolBefore {
		t.Errorf("pool changed by %d; want 0",
			poolBefore-env.DiceTotal(0))
	}

	// 伏兵之术 used flag should NOT be set (gate blocked)
	used := env.G.Counters[findCounterIDPerPlayer(env, "伏兵之术_used", 0)].Value
	if used != 0 {
		t.Errorf("伏兵之术_used = %d, want 0 (gate short-circuited)", used)
	}
}

// TestDiscount_伏兵之术_Consumed_WhenMakesFree verifies 伏兵之术's
// normal case: it makes a switch free, and its used flag flips.
func TestDiscount_伏兵之术_Consumed_WhenMakesFree(t *testing.T) {
	env := NewGame(t, []string{"赤蝶", "墨客"}, []string{"墨客"})

	env.setCounterPerPlayer(t, "伏兵之术_active", 0, 1)
	env.PlayUntilTurn(0, 10)

	actions := env.G.GetLegalActions()
	switchIdx := -1
	for i, a := range actions {
		if a.Kind == engine.ActionSwitch && a.Index == 1 {
			switchIdx = i
			break
		}
	}
	if switchIdx < 0 {
		t.Fatal("switch not available")
	}
	env.Step(switchIdx)

	used := env.G.Counters[findCounterIDPerPlayer(env, "伏兵之术_used", 0)].Value
	if used != 1 {
		t.Errorf("伏兵之术_used = %d, want 1 (charge consumed)", used)
	}
}

// findCounterIDPerPlayer finds the ID of a PerPlayer counter by
// display name for the given player.
func findCounterIDPerPlayer(env *GameEnv, name string, p int) int {
	for id, n := range env.G.CounterNames {
		if n != name {
			continue
		}
		m := env.G.GetCounterChar(id)
		if m[0] == p && m[1] == -1 {
			return id
		}
	}
	return -1
}
