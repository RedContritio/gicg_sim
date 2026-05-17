package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestRuntimeClone verifies that cloning a Runtime produces an independent
// game that can be stepped without affecting the original. Uses Clone on
// the runtime obtained from a NewGameWithDeck environment.
func TestRuntimeClone_IndependentStep(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})

	// Get HP of both chars pre-clone
	origHP0 := env.HP(0, 0)
	origHP1 := env.HP(1, 0)

	// Clone: expect identical state
	cloneRT := env.RT.Clone()
	cloneG := cloneRT.Game
	if cloneG.Counters[env.RT.Chars.BySlot[0][0].HPCounterID].Value != origHP0 {
		t.Fatalf("clone HP0 mismatch")
	}
	if cloneG.Counters[env.RT.Chars.BySlot[1][0].HPCounterID].Value != origHP1 {
		t.Fatalf("clone HP1 mismatch")
	}

	// Step in the clone only. Use the clone's runtime context so hook
	// dispatch routes to the clone via Game.Extra.
	cloneRT.CurrentContextPlayer = cloneG.Turn
	actions := cloneG.GetLegalActions()
	if len(actions) == 0 {
		t.Fatal("clone has no legal actions")
	}
	// Find any skill action and execute
	for i, a := range actions {
		if a.Kind == engine.ActionSkill {
			cloneG.Step(i)
			break
		}
	}

	// Original should be unchanged
	if env.HP(0, 0) != origHP0 {
		t.Errorf("original HP0 changed after clone step: got %d, want %d", env.HP(0, 0), origHP0)
	}
	if env.HP(1, 0) != origHP1 {
		t.Errorf("original HP1 changed after clone step: got %d, want %d", env.HP(1, 0), origHP1)
	}

	// Original's turn counter should also be unchanged
	if env.G.Round != cloneG.Round && env.G.Round != 1 {
		// clone may have advanced phases, but original should stay at round 1
		t.Errorf("original round changed: %d", env.G.Round)
	}
}

// TestSnapshotRestore_RoundTrip verifies that taking a snapshot, mutating
// the live game, then restoring from the snapshot recovers the original
// dynamic state.
func TestSnapshotRestore_RoundTrip(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})

	origHP1 := env.HP(1, 0)
	origRound := env.G.Round
	origTurn := env.G.Turn

	snap := env.G.DeepCopy()

	// Mutate live game with a skill
	for i, a := range env.G.GetLegalActions() {
		if a.Kind == engine.ActionSkill {
			env.Step(i)
			break
		}
	}
	if env.HP(1, 0) == origHP1 {
		t.Fatal("expected HP to change after skill — setup invalid")
	}

	env.G.RestoreFrom(snap)

	if env.HP(1, 0) != origHP1 {
		t.Errorf("HP1 not restored: got %d want %d", env.HP(1, 0), origHP1)
	}
	if env.G.Round != origRound {
		t.Errorf("Round not restored: got %d want %d", env.G.Round, origRound)
	}
	if env.G.Turn != origTurn {
		t.Errorf("Turn not restored: got %d want %d", env.G.Turn, origTurn)
	}
}

// TestRuntimeClone_SharedRuleset verifies Ruleset is shared (pointer equality)
// between original and clone, but Game is separate.
func TestRuntimeClone_SharedRuleset(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	cloneRT := env.RT.Clone()

	if cloneRT.Ruleset != env.RT.Ruleset {
		t.Errorf("Ruleset should be shared by pointer")
	}
	if cloneRT.Game == env.G {
		t.Errorf("Game should be a distinct pointer after clone")
	}
	if cloneRT.Game.Hooks != env.G.Hooks {
		t.Errorf("Hooks registry should be shared (aliased) on clone")
	}
	// Extra should point to the clone runtime, not the original
	if cloneRT.Game.Extra != any(cloneRT) {
		t.Errorf("cloned Game.Extra should point to clone Runtime")
	}
	if env.G.Extra != any(env.RT) {
		t.Errorf("original Game.Extra should still point to original Runtime")
	}
}
