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
			env.G.WriteCounter(id, engine.OpSet, 1)
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
			env.G.WriteCounter(id, engine.OpSet, value)
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

// Other discounts settle before 乘胜追击's fourth-costed-operation discount.
func TestDiscount_乘胜追击_RestrictedFirst(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.setCounterPerPlayer(t, "乘胜追击_active", 0, 1)
	env.setCounterPerPlayer(t, "乘胜追击_count", 0, 3)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 8})
	if !env.StepSkill("枪") {
		t.Fatal("枪 unavailable")
	}
	if env.DiceTotal(0) != 8 {
		t.Fatal("1 fire + 2 any must reduce to zero")
	}
}

func TestDiscount_速速茶点_Before_乘胜追击(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.setBuffToOne(t, "速速茶点_buff", 0, 0)
	env.setCounterPerPlayer(t, "乘胜追击_active", 0, 1)
	env.setCounterPerPlayer(t, "乘胜追击_count", 0, 3)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 8})
	if !env.StepSkill("枪") {
		t.Fatal("枪 unavailable")
	}
	if env.DiceTotal(0) != 8 || env.counterByChar("速速茶点_buff", 0, 0) != 0 {
		t.Fatal("tea applies first; remaining cost reduces to zero")
	}
}

func TestDiscount_伏兵之术_FreeSwitchDoesNotCount(t *testing.T) {
	env := NewGame(t, []string{"赤蝶", "墨客"}, []string{"墨客"})
	env.setCounterPerPlayer(t, "伏兵之术_active", 0, 1)
	env.setCounterPerPlayer(t, "乘胜追击_active", 0, 1)
	env.setCounterPerPlayer(t, "乘胜追击_count", 0, 3)
	before := env.DiceTotal(0)
	auditSwitch(t, env, 0, 1)
	if env.DiceTotal(0) != before {
		t.Fatal("switch should be free")
	}
	if env.G.ReadCounter(findCounterIDPerPlayer(env, "伏兵之术_used", 0)) != 1 {
		t.Fatal("ambush charge not consumed")
	}
	if env.G.ReadCounter(findCounterIDPerPlayer(env, "乘胜追击_count", 0)) != 3 {
		t.Fatal("already-free switch counted")
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
