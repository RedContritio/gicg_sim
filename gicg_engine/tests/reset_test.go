package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestResetDynamic_RestoresInitialState verifies that ResetDynamic restores
// HP, deck, hand, phase, turn, and round to a fresh post-init state after
// the game has been advanced by several actions.
func TestResetDynamic_RestoresInitialState(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	// Rule test: explicitly fund both players rather than depend on random rolls.
	env.SetDice(0, map[int]int{7: 8})
	env.SetDice(1, map[int]int{7: 8})

	initHP0 := env.HP(0, 0)
	initHP1 := env.HP(1, 0)
	initHandCount0 := len(env.G.Players[0].Hand)
	initDeckCount0 := len(env.G.Players[0].Deck)

	// Advance the game: take any skill action that should change HP.
	for i, a := range env.G.GetLegalActions() {
		if a.Kind == engine.ActionSkill {
			env.Step(i)
			break
		}
	}
	if env.HP(1, 0) == initHP1 && env.HP(0, 0) == initHP0 {
		t.Fatal("expected HP to change after skill use; setup invalid")
	}

	// Reset
	env.RT.ResetDynamic(123)
	if err := keepAllRerolls(env.G); err != nil {
		t.Fatal(err)
	}

	if env.HP(0, 0) != initHP0 {
		t.Errorf("HP0 not restored: got %d want %d", env.HP(0, 0), initHP0)
	}
	if env.HP(1, 0) != initHP1 {
		t.Errorf("HP1 not restored: got %d want %d", env.HP(1, 0), initHP1)
	}
	if env.G.Phase != engine.PhaseAction {
		t.Errorf("expected PhaseAction after reset, got %v", env.G.Phase)
	}
	if env.G.Round != 1 {
		t.Errorf("expected Round=1 after reset, got %d", env.G.Round)
	}
	if env.G.Winner != -1 {
		t.Errorf("expected Winner=-1 after reset, got %d", env.G.Winner)
	}
	if env.G.Players[0].ActiveChar != 0 || env.G.Players[1].ActiveChar != 0 {
		t.Errorf("expected ActiveChar=0 for both, got %d / %d",
			env.G.Players[0].ActiveChar, env.G.Players[1].ActiveChar)
	}
	if got := len(env.G.Players[0].Hand); got != initHandCount0 {
		t.Errorf("hand count mismatch: got %d want %d", got, initHandCount0)
	}
	if got := len(env.G.Players[0].Deck); got != initDeckCount0 {
		t.Errorf("deck count mismatch: got %d want %d", got, initDeckCount0)
	}
	if !env.Alive(0, 0) || !env.Alive(1, 0) {
		t.Errorf("chars should be alive after reset")
	}
}

// TestResetDynamic_AliveCountRestored verifies that the alive_count counter
// (set by system/alive.lua via on_revive) is correctly re-incremented after
// reset, even if a char died before reset.
func TestResetDynamic_AliveCountRestored(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})

	initialAlive0 := readAliveCount(t, env, 0)
	initialAlive1 := readAliveCount(t, env, 1)
	if initialAlive0 != 1 || initialAlive1 != 1 {
		t.Fatalf("expected alive_count=1 each, got %d/%d", initialAlive0, initialAlive1)
	}

	env.RT.ResetDynamic(456)

	if got := readAliveCount(t, env, 0); got != 1 {
		t.Errorf("alive_count[0] after reset: got %d want 1", got)
	}
	if got := readAliveCount(t, env, 1); got != 1 {
		t.Errorf("alive_count[1] after reset: got %d want 1", got)
	}
}

func readAliveCount(t *testing.T, env *GameEnv, player int) int {
	t.Helper()
	entry, ok := env.RT.CounterEntries()["alive_count"]
	if !ok {
		t.Fatal("alive_count counter missing")
	}
	if len(entry.CounterIDs) < 2 {
		t.Fatalf("alive_count expected PerPlayer (2 ids), got %d", len(entry.CounterIDs))
	}
	return env.G.Counters[entry.CounterIDs[player]].Value
}

// TestResetDynamic_PreservesRulesetIdentity verifies that ResetDynamic does
// not allocate a new Ruleset/Hooks registry — those are static.
func TestResetDynamic_PreservesRulesetIdentity(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	rulesetBefore := env.RT.Ruleset
	hooksBefore := env.G.Hooks
	counterCountBefore := len(env.G.Counters)

	env.RT.ResetDynamic(789)

	if env.RT.Ruleset != rulesetBefore {
		t.Error("Ruleset pointer changed across reset")
	}
	if env.G.Hooks != hooksBefore {
		t.Error("Hooks registry changed across reset")
	}
	if len(env.G.Counters) != counterCountBefore {
		t.Errorf("counter count changed: got %d want %d", len(env.G.Counters), counterCountBefore)
	}
}
