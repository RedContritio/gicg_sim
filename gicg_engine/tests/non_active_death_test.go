package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestNonActiveDeath_NoForcedSwitch is the regression test for the
// phase0c deadlock bug: multi-target wipes like 刻师傅 雷暴 killing
// only the NON-active enemy chars used to queue a pointless forced
// switch for the still-alive active, which then produced zero legal
// actions (forcedSwitchActions excludes the current active). Engine
// entered PhaseAction with no moves and no GameOver, and VectorizedRollout
// saw this as a truncation.
//
// Fix (training/rollout.go was not the actual fix site — see
// gicg_engine/interp/builtins.go registerDeathCheck): only queue the
// forced switch when the DYING char was the current active.
//
// Reproducer: set up 3v3, damage only non-active chars of P1, verify
// that GetLegalActions() returns a non-empty list including EndTurn,
// and that env.Phase stays PhaseAction (not a bogus PendingSwitch state).
func TestNonActiveDeath_NoForcedSwitch(t *testing.T) {
	env := NewGame(t,
		[]string{"刻师傅", "赤蝶", "墨客"},
		[]string{"刻师傅", "赤蝶", "墨客"})

	// Advance past SelectActive → both players' active = idx 0.
	// Step once per player to pick active chars (FindAction picks idx 0
	// since that's the first legal Switch in SelectActive mode).
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}

	// Kill P1's non-active chars (idx 1 and idx 2) directly via HP
	// counter writes. This bypasses any skill targeting logic; we're
	// exercising the death-check hook, which is what registers the
	// pending forced switch.
	for _, ci := range []int{1, 2} {
		entry := env.RT.Chars.BySlot[1][ci]
		if entry == nil {
			t.Fatalf("char slot 1/%d missing", ci)
		}
		hpID := entry.HPCounterID
		cur := env.G.Counters[hpID].Value
		// WriteCounter(OpSub, cur) drops HP to 0 and triggers the
		// registerDeathCheck hook.
		env.G.WriteCounter(hpID, engine.OpSub, cur)
	}

	// Invariants after the two non-active deaths:
	// - P1's active (idx 0) is still alive.
	// - Game is NOT over (P1 still has one alive char).
	// - Engine should NOT be in a pending-forced-switch state, because
	//   the dying chars were non-active.
	// - GetLegalActions() must return at least EndTurn (never empty).
	if !env.Alive(1, 0) {
		t.Fatal("P1 active (idx 0) should still be alive")
	}
	if env.Alive(1, 1) || env.Alive(1, 2) {
		t.Fatal("P1 non-actives (idx 1, 2) should be dead")
	}
	if env.G.Phase == engine.PhaseGameOver {
		t.Fatal("game should NOT be over (P1 active still alive)")
	}
	if env.G.PendingAction != nil {
		t.Fatalf("no forced switch should be pending after non-active "+
			"deaths, got %+v", env.G.PendingAction)
	}

	actions := env.G.GetLegalActions()
	if len(actions) == 0 {
		t.Fatal("legal actions must not be empty — pre-fix bug returned " +
			"an empty list here because forcedSwitchActions excluded the " +
			"only alive char (the current active)")
	}
	// EndTurn is always appended at the end of GetLegalActions when
	// not in a pending-forced-switch state.
	var haveEndTurn bool
	for _, a := range actions {
		if a.Kind == engine.ActionEndTurn {
			haveEndTurn = true
			break
		}
	}
	if !haveEndTurn {
		t.Error("expected EndTurn in legal actions")
	}
}

// TestActiveDeath_DoesForceSwitch is the complementary positive test:
// killing the ACTIVE char must still queue a forced switch (so the
// fix didn't accidentally disable the normal path).
func TestActiveDeath_DoesForceSwitch(t *testing.T) {
	env := NewGame(t,
		[]string{"刻师傅", "赤蝶", "墨客"},
		[]string{"刻师傅", "赤蝶", "墨客"})
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}

	// Kill P1's active (idx 0).
	entry := env.RT.Chars.BySlot[1][0]
	hpID := entry.HPCounterID
	cur := env.G.Counters[hpID].Value
	env.G.ExecuteEffect(engine.EventFrame{Player: 0, Char: 0}, func(g *engine.Game) {
		g.WriteCounter(hpID, engine.OpSub, cur)
	})

	if env.Alive(1, 0) {
		t.Fatal("P1 active should be dead")
	}
	if env.G.Phase == engine.PhaseGameOver {
		t.Fatal("game should not be over — two non-actives still alive")
	}
	if env.G.PendingAction == nil {
		t.Fatal("forced switch should be pending after active death")
	}
	if env.G.PendingAction.Kind != engine.ActionSwitch ||
		env.G.PendingAction.PlayerIdx != 1 ||
		!env.G.PendingAction.Forced {
		t.Fatalf("unexpected PendingAction: %+v", env.G.PendingAction)
	}

	// Legal actions should be the two alive non-actives (idx 1 and 2).
	actions := env.G.GetLegalActions()
	if len(actions) != 2 {
		t.Fatalf("expected 2 forced-switch options, got %d", len(actions))
	}
	for _, a := range actions {
		if a.Kind != engine.ActionSwitch || !a.Forced {
			t.Errorf("expected forced Switch, got %+v", a)
		}
	}
}
