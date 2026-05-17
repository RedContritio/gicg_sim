package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestDeepCopy_PreservesPendingAction verifies that DeepCopy preserves
// PendingAction (a pending forced-switch waiting for the victim player
// to pick a replacement char). Before the Phase I fix, DeepCopy silently
// nulled this field, causing MCTS snapshots taken at pending-switch
// decision points to lose the state on restore.
func TestDeepCopy_PreservesPendingAction(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// Manually set a pending action
	g.PendingAction = &engine.Action{
		Kind:      engine.ActionSwitch,
		PlayerIdx: 1,
		Forced:    true,
	}

	snap := g.DeepCopy()
	if snap.PendingAction == nil {
		t.Fatal("DeepCopy dropped PendingAction")
	}
	if snap.PendingAction.Kind != engine.ActionSwitch {
		t.Errorf("PendingAction.Kind = %v, want ActionSwitch",
			snap.PendingAction.Kind)
	}
	if snap.PendingAction.PlayerIdx != 1 {
		t.Errorf("PendingAction.PlayerIdx = %d, want 1",
			snap.PendingAction.PlayerIdx)
	}
	if !snap.PendingAction.Forced {
		t.Error("PendingAction.Forced lost")
	}

	// Mutating original's PendingAction must NOT affect the snap
	g.PendingAction.PlayerIdx = 99
	if snap.PendingAction.PlayerIdx != 1 {
		t.Error("snap.PendingAction shares pointer with original (not deep copied)")
	}

	// Mutating snap's must NOT affect original
	snap.PendingAction.PlayerIdx = 42
	if g.PendingAction.PlayerIdx != 99 {
		t.Error("original mutated through snap's PendingAction pointer")
	}
}

// TestDeepCopy_PreservesPendingCardTarget verifies DeepCopy preserves
// PendingCardTarget (a card play waiting for the player to pick a
// target). Same underlying concern as PendingAction.
func TestDeepCopy_PreservesPendingCardTarget(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	g.PendingCardTarget = &engine.PendingCard{
		PlayerIdx:    0,
		CardRef:      42,
		BattleAction: true,
		TargetMode:   2,
	}

	snap := g.DeepCopy()
	if snap.PendingCardTarget == nil {
		t.Fatal("DeepCopy dropped PendingCardTarget")
	}
	if snap.PendingCardTarget.CardRef != 42 {
		t.Errorf("CardRef = %d, want 42", snap.PendingCardTarget.CardRef)
	}
	if snap.PendingCardTarget.TargetMode != 2 {
		t.Errorf("TargetMode = %d, want 2", snap.PendingCardTarget.TargetMode)
	}

	// Deep copy: mutation in original must not affect snap
	g.PendingCardTarget.CardRef = 99
	if snap.PendingCardTarget.CardRef != 42 {
		t.Error("snap shares PendingCardTarget pointer with original")
	}
}

// TestActingPlayer_NormalCase: without pending, ActingPlayer == Turn.
func TestActingPlayer_NormalCase(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	g.Turn = 0
	g.PendingAction = nil
	if got := g.ActingPlayer(); got != 0 {
		t.Errorf("ActingPlayer = %d, want 0 (Turn)", got)
	}

	g.Turn = 1
	if got := g.ActingPlayer(); got != 1 {
		t.Errorf("ActingPlayer = %d, want 1 (Turn)", got)
	}
}

// TestActingPlayer_PendingSwitchOverridesTurn: when a forced switch is
// pending, ActingPlayer returns the victim (PendingAction.PlayerIdx),
// not the current Turn. This is the MCTS correctness fix from Phase I.
func TestActingPlayer_PendingSwitchOverridesTurn(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// Attacker is P0, victim (pending switch) is P1
	g.Turn = 0
	g.PendingAction = &engine.Action{
		Kind:      engine.ActionSwitch,
		PlayerIdx: 1,
		Forced:    true,
	}

	if got := g.ActingPlayer(); got != 1 {
		t.Errorf("ActingPlayer = %d, want 1 (victim via PendingAction), "+
			"Turn=%d (attacker, stale)", got, g.Turn)
	}
}

// TestHasPending: verify both pending conditions are detected.
func TestHasPending(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	g.PendingAction = nil
	g.PendingCardTarget = nil
	if g.HasPending() {
		t.Error("HasPending = true when nothing pending")
	}

	g.PendingAction = &engine.Action{Kind: engine.ActionSwitch}
	if !g.HasPending() {
		t.Error("HasPending = false when PendingAction set")
	}

	g.PendingAction = nil
	g.PendingCardTarget = &engine.PendingCard{CardRef: 1}
	if !g.HasPending() {
		t.Error("HasPending = false when PendingCardTarget set")
	}
}
