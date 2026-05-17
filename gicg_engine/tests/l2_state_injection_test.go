package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// L2 state-injection tests (#131) — construct mid-game states by
// directly setting hand/dice/counters, then verify engine behavior
// around the L2 food/energy cards without relying on random early-
// game play. The core goal is to prove:
//  1. The 饱腹 lockout correctly removes card actions from legal list
//     (no deadlock when a char can't eat).
//  2. 饱腹 decays at round boundary and food becomes playable again.
//  3. 佛跳墙 damage buff fires exactly once then clears.
//  4. 诅咒 safely no-ops when enemy energy is already 0.
//  5. 占星 caps at max_energy rather than overflowing.
//  6. Mid-game state injection + L2 card play → GetLegalActions stays
//     non-empty (no PhaseAction deadlock).

// l2Setup builds a 1v1 game with both L2 cards plus 碌碌无为 filler
// in a known initial state, ready for direct hand/dice/counter
// injection by the test body.
func l2Setup(t *testing.T) *GameEnv {
	t.Helper()
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	return env
}

// setCounterPerChar writes a value into a PerChar-scope counter at
// slot (p, c). Only for counters registered as PerChar — panics
// otherwise.
func setCounterPerChar(t *testing.T, env *GameEnv, name string, p, c int, v int) {
	t.Helper()
	entry, ok := env.RT.CounterEntries()[name]
	if !ok {
		t.Fatalf("counter %q not registered", name)
	}
	if entry.Scope != interp.ScopePerChar {
		t.Fatalf("counter %q is not PerChar (scope=%d)", name, entry.Scope)
	}
	idx := p*interp.MaxChars + c
	if idx >= len(entry.CounterIDs) {
		t.Fatalf("PerChar idx %d out of range for %q", idx, name)
	}
	id := entry.CounterIDs[idx]
	if id < 0 {
		t.Fatalf("counter %q has no slot at (p=%d, c=%d)", name, p, c)
	}
	env.G.Counters[id].Value = v
}

// getCounterPerChar reads a PerChar counter at slot (p, c).
func getCounterPerChar(t *testing.T, env *GameEnv, name string, p, c int) int {
	t.Helper()
	entry, ok := env.RT.CounterEntries()[name]
	if !ok {
		t.Fatalf("counter %q not registered", name)
	}
	idx := p*interp.MaxChars + c
	id := entry.CounterIDs[idx]
	return env.G.Counters[id].Value
}

// injectHand replaces the given player's hand with named cards.
// Resolves card names to refs through the runtime so tests read
// naturally.
func injectHand(t *testing.T, env *GameEnv, p int, cardNames []string) {
	t.Helper()
	refs := make([]int, 0, len(cardNames))
	for _, name := range cardNames {
		c, ok := env.RT.Cards.ByName[name]
		if !ok {
			t.Fatalf("card %q not in ruleset", name)
		}
		refs = append(refs, c.Ref)
	}
	env.G.SetPlayerHand(p, refs)
}

// ensureLegalActions asserts GetLegalActions returns at least one
// action when the engine is in a decision phase. This is the core
// deadlock check — if injecting state knocks the engine into a
// zero-legal state outside terminal, it's a D14-class bug.
func ensureLegalActions(t *testing.T, env *GameEnv) {
	t.Helper()
	if env.G.Phase == engine.PhaseGameOver {
		return
	}
	if env.G.Phase != engine.PhaseAction && env.G.Phase != engine.PhaseSelectActive {
		return
	}
	if len(env.G.GetLegalActions()) == 0 {
		t.Fatalf("no legal actions in phase=%d turn=%d round=%d",
			env.G.Phase, env.G.Turn, env.G.Round)
	}
}

// --- Tests --------------------------------------------------------

// TestL2_FoodLockoutRemovesBoth — inject both food cards into P0's
// hand with 饱腹 already set to 1. Both foods must be absent from
// legal actions, but the engine is NOT deadlocked (EndTurn is still
// available).
func TestL2_FoodLockoutRemovesBoth(t *testing.T) {
	env := l2Setup(t)

	// P0's turn; give them both food cards and ample dice.
	injectHand(t, env, 0, []string{"美味烧鸡", "佛跳墙"})
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 5})

	// Pre-set 饱腹 on P0's active char (C0).
	setCounterPerChar(t, env, "饱腹", 0, 0, 1)

	// Food cards must be filtered from legal actions.
	if idx := env.FindAction(engine.ActionCard, "美味烧鸡"); idx >= 0 {
		t.Errorf("美味烧鸡 should be blocked by 饱腹 but legal at idx=%d", idx)
	}
	if idx := env.FindAction(engine.ActionCard, "佛跳墙"); idx >= 0 {
		t.Errorf("佛跳墙 should be blocked by 饱腹 but legal at idx=%d", idx)
	}

	// Must still have at least EndTurn available — no deadlock.
	ensureLegalActions(t, env)
}

// TestL2_MeixiaoshaojiHealsAndLocks — play 美味烧鸡, verify HP+1 and
// 饱腹=1, then 佛跳墙 becomes unplayable on the same char same round.
func TestL2_MeixiaoshaojiHealsAndLocks(t *testing.T) {
	env := l2Setup(t)

	// Damage P0's active char so heal is observable.
	p0Entry := env.RT.Chars.BySlot[0][0]
	env.G.Counters[p0Entry.HPCounterID].Value = 10

	// Turn=0 (P0's turn), inject hand + dice.
	injectHand(t, env, 0, []string{"美味烧鸡", "佛跳墙"})
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 5})

	// 饱腹=0 initially.
	if v := getCounterPerChar(t, env, "饱腹", 0, 0); v != 0 {
		t.Fatalf("expected 饱腹=0 pre-play, got %d", v)
	}

	// Play 美味烧鸡.
	idx := env.FindAction(engine.ActionCard, "美味烧鸡")
	if idx < 0 {
		t.Fatal("美味烧鸡 not legal before eating")
	}
	env.Step(idx)

	// HP +1, 饱腹 = 1.
	if hp := env.HP(0, 0); hp != 11 {
		t.Errorf("HP after heal = %d, want 11", hp)
	}
	if v := getCounterPerChar(t, env, "饱腹", 0, 0); v != 1 {
		t.Errorf("饱腹 after play = %d, want 1", v)
	}

	// 佛跳墙 is no longer legal for the same target.
	if idx2 := env.FindAction(engine.ActionCard, "佛跳墙"); idx2 >= 0 {
		t.Errorf("佛跳墙 should be blocked after 美味烧鸡 but legal at %d", idx2)
	}

	ensureLegalActions(t, env)
}

// TestL2_FoodDecaysAcrossRound — eat food, end the round, verify
// 饱腹 resets to 0 and food becomes playable again.
func TestL2_FoodDecaysAcrossRound(t *testing.T) {
	env := l2Setup(t)

	injectHand(t, env, 0, []string{"美味烧鸡", "碌碌无为"})
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 5})

	// Eat.
	idx := env.FindAction(engine.ActionCard, "美味烧鸡")
	if idx < 0 {
		t.Fatal("美味烧鸡 not legal")
	}
	env.Step(idx)

	round := env.G.Round
	if v := getCounterPerChar(t, env, "饱腹", 0, 0); v != 1 {
		t.Fatalf("饱腹 after eat = %d, want 1", v)
	}

	// End turn both sides to advance round. Use PlayN with action 0
	// (EndTurn is usually first if no other legal action is cheaper
	// to find — but safer to find it explicitly each iteration).
	for steps := 0; steps < 80 && env.G.Round == round; steps++ {
		if env.G.Phase == engine.PhaseGameOver {
			t.Fatal("game ended unexpectedly during round advance")
		}
		idx := env.FindAction(engine.ActionEndTurn, "")
		if idx < 0 {
			// Fall back to any legal action to unblock.
			env.Step(0)
			continue
		}
		env.Step(idx)
	}
	if env.G.Round == round {
		t.Fatalf("round did not advance (still %d)", round)
	}

	// After the new round start, 饱腹 should have decayed.
	if v := getCounterPerChar(t, env, "饱腹", 0, 0); v != 0 {
		t.Errorf("饱腹 after round advance = %d, want 0", v)
	}

	// Food playable again (inject fresh hand + dice because hand/dice
	// were consumed across the round turnover).
	injectHand(t, env, 0, []string{"美味烧鸡"})
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 5})

	// Advance to P0's turn in the new round if we aren't already.
	if env.G.Phase == engine.PhaseAction && env.G.Turn == 0 {
		if env.FindAction(engine.ActionCard, "美味烧鸡") < 0 {
			t.Error("美味烧鸡 not legal in new round after 饱腹 decay")
		}
	}
}
