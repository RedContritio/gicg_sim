package tests

import (
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestInvariants_SyntheticDeadlock verifies the L1 invariant checker
// catches the D14-style "PhaseAction with zero legal actions" shape.
// Can't construct a raw Game by hand (GetLegalActions depends on the
// hook registry), so we build a real 3v3, then post-hoc force the
// engine into the broken state by writing HP counters and forcing a
// pending switch whose target list ends up empty.
//
// This is a meta-test for the invariant checker itself: if a future
// regression reintroduces D14 via a different code path, the auto
// check in GameEnv.Step would only catch it if some test happens to
// walk through that state. This test verifies the checker's detection
// logic independently.
func TestInvariants_SyntheticDeadlock(t *testing.T) {
	// Use a 1v1 so killing "all non-actives" of a player is trivial.
	// After we kill P1's only char, the game should be GameOver, not
	// deadlocked — so we have to make the state inconsistent on
	// purpose: mark it as still PhaseAction with a pending forced
	// switch for P1 even though no switch target exists.
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	// Suppress the auto-invariant check — we're intentionally going to
	// reach a broken state.
	env.T = nil
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}

	// Force the engine into a deadlocked shape:
	//   - P1's only char is dead
	//   - PendingAction is a forced switch for P1
	//   - Phase is still PhaseAction (not GameOver)
	env.G.Players[1].Chars[0].Alive = false
	env.G.PendingAction = &engine.Action{
		Kind:      engine.ActionSwitch,
		PlayerIdx: 1,
		Forced:    true,
	}
	env.G.Phase = engine.PhaseAction

	errs := invariantErrors(env.G, 0)
	if len(errs) == 0 {
		t.Fatal("expected invariantErrors to report violations, got none")
	}
	joined := strings.Join(errs, " | ")
	// The pending-switch-no-targets detector should fire.
	if !strings.Contains(joined, "no alive chars at all") {
		t.Errorf("expected 'no alive chars' error, got: %s", joined)
	}
}

// TestInvariants_SyntheticDeadActive verifies the "dead active in
// PhaseAction with no pending switch" detector — D14's other hazard:
// a char died but the engine forgot to queue a forced switch.
func TestInvariants_SyntheticDeadActive(t *testing.T) {
	env := NewGame(t, []string{"刻师傅", "赤蝶", "墨客"}, []string{"刻师傅", "赤蝶", "墨客"})
	env.T = nil
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}

	// Kill P1's active directly but suppress PendingAction (simulate
	// a bug where registerDeathCheck failed to queue the switch).
	env.G.Players[1].Chars[env.G.Players[1].ActiveChar].Alive = false
	env.G.PendingAction = nil
	env.G.Phase = engine.PhaseAction

	errs := invariantErrors(env.G, 0)
	var matched bool
	for _, e := range errs {
		if strings.Contains(e, "is dead in PhaseAction") {
			matched = true
			break
		}
	}
	if !matched {
		t.Errorf("expected 'dead in PhaseAction' error, got: %v", errs)
	}
}

// TestInvariants_GameOverSilences confirms a finished game is never
// flagged — otherwise legitimate terminal states would fail every
// test that runs to completion.
func TestInvariants_GameOverSilences(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.T = nil
	env.G.Phase = engine.PhaseGameOver
	env.G.Winner = 0
	// Even with obviously broken state (dead active, no PendingAction,
	// zero legal actions), GameOver must silence all invariants.
	env.G.Players[1].Chars[0].Alive = false

	if errs := invariantErrors(env.G, 0); len(errs) != 0 {
		t.Errorf("expected no errors in GameOver phase, got: %v", errs)
	}
}
