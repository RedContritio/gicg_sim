package tests

import (
	"encoding/json"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

// TestExportView_InitialState validates that a fresh game produces a
// sensible StateView immediately after setup — before any action has
// been taken. This is the minimum viable contract for the web UI's
// "new game" screen.
func TestExportView_InitialState(t *testing.T) {
	env := NewGame(t,
		[]string{"赤蝶", "墨客"},
		[]string{"猫咪", "刻师傅"})

	// Advance past SelectActive so we're in PhaseAction with alive
	// counts populated.
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}

	view := record.ExportView(env.RT)

	if view.Phase != "action" {
		t.Errorf("phase = %q, want action", view.Phase)
	}
	if view.Round < 1 {
		t.Errorf("round = %d, want >= 1", view.Round)
	}
	if view.Winner != -1 {
		t.Errorf("winner = %d, want -1 (ongoing)", view.Winner)
	}

	// Both players must have 2 chars with the expected names.
	if got := len(view.Players[0].Chars); got != 2 {
		t.Fatalf("P0 char count = %d, want 2", got)
	}
	if view.Players[0].Chars[0].Name != "赤蝶" {
		t.Errorf("P0 char 0 = %q, want 赤蝶", view.Players[0].Chars[0].Name)
	}
	if view.Players[0].Chars[1].Name != "墨客" {
		t.Errorf("P0 char 1 = %q, want 墨客", view.Players[0].Chars[1].Name)
	}
	if view.Players[1].Chars[0].Name != "猫咪" {
		t.Errorf("P1 char 0 = %q, want 猫咪", view.Players[1].Chars[0].Name)
	}

	// All chars start alive with full HP.
	for pi, pv := range view.Players {
		for ci, cv := range pv.Chars {
			if !cv.Alive {
				t.Errorf("P%d char %d should be alive", pi, ci)
			}
			if cv.HP <= 0 || cv.HP > cv.HPMax || cv.HPMax <= 0 {
				t.Errorf("P%d char %d HP=%d/%d invalid", pi, ci, cv.HP, cv.HPMax)
			}
		}
	}

	// Exactly one char per side should be marked active.
	for pi, pv := range view.Players {
		activeCount := 0
		for _, cv := range pv.Chars {
			if cv.Active {
				activeCount++
			}
		}
		if activeCount != 1 {
			t.Errorf("P%d active count = %d, want 1", pi, activeCount)
		}
	}
}

// TestExportView_JSONRoundTrip verifies the view serializes cleanly to
// JSON and back — this is the wire format the web backend will use.
func TestExportView_JSONRoundTrip(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}

	view := record.ExportView(env.RT)
	blob, err := json.Marshal(view)
	if err != nil {
		t.Fatalf("Marshal: %v", err)
	}
	if len(blob) == 0 {
		t.Fatal("empty JSON blob")
	}

	var restored record.StateView
	if err := json.Unmarshal(blob, &restored); err != nil {
		t.Fatalf("Unmarshal: %v", err)
	}
	if restored.Phase != view.Phase {
		t.Errorf("phase mismatch after round trip: %q vs %q", restored.Phase, view.Phase)
	}
	if restored.Players[0].Chars[0].Name != view.Players[0].Chars[0].Name {
		t.Error("char name mismatch after round trip")
	}
}

// TestExportView_AfterDamage captures the canonical "show me what just
// happened" case the web replay player needs: a skill fires, HP drops,
// and the view reflects the new state.
func TestExportView_AfterDamage(t *testing.T) {
	env := NewGame(t,
		[]string{"赤蝶", "墨客"},
		[]string{"猫咪"})
	// Rule test: explicitly fund both players rather than depend on random rolls.
	env.SetDice(0, map[int]int{7: 8})
	env.SetDice(1, map[int]int{7: 8})
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}

	before := record.ExportView(env.RT)
	p1HPBefore := before.Players[1].Chars[0].HP

	// P0's active (赤蝶) casts 枪 on P1 — should deal damage.
	if !env.StepSkill("枪") {
		t.Fatal("could not find 枪 action")
	}

	after := record.ExportView(env.RT)
	p1HPAfter := after.Players[1].Chars[0].HP
	if p1HPAfter >= p1HPBefore {
		t.Errorf("P1 HP did not drop after 枪: before=%d after=%d",
			p1HPBefore, p1HPAfter)
	}
}

// TestExportView_DiscardReflectsMovedCards verifies that cards moved
// into a player's discard pile (via direct Game-level mutation that
// mirrors what card-play and tune paths do) appear in the exported
// view's Discard field with matching refs + names. This is the
// field IS-MCTS determinization uses to subtract publicly-committed
// cards from the sampled hand/deck.
func TestExportView_DiscardReflectsMovedCards(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}
	g := env.G

	// Fresh state: discard must be empty for both players.
	view := record.ExportView(env.RT)
	for pi := 0; pi < 2; pi++ {
		if len(view.Players[pi].Discard) != 0 {
			t.Errorf("P%d discard not empty on fresh game: %d entries",
				pi, len(view.Players[pi].Discard))
		}
	}

	// Move one of P0's hand cards into P0's discard (mirrors what
	// play_card / executeTune do internally).
	if len(g.Players[0].Hand) == 0 {
		t.Fatal("P0 has no hand cards to discard")
	}
	moved := g.Players[0].Hand[0]
	g.Players[0].Hand = g.Players[0].Hand[1:]
	g.Players[0].Discard = append(g.Players[0].Discard, moved)

	view = record.ExportView(env.RT)
	if len(view.Players[0].Discard) != 1 {
		t.Fatalf("P0 discard size = %d, want 1", len(view.Players[0].Discard))
	}
	got := view.Players[0].Discard[0]
	if got.Ref != moved.Ref {
		t.Errorf("discard[0].Ref = %d, want %d", got.Ref, moved.Ref)
	}
	if got.Name == "" {
		t.Error("discard[0].Name is empty — card name lookup failed")
	}
	// P1's discard still untouched.
	if len(view.Players[1].Discard) != 0 {
		t.Errorf("P1 discard disturbed: %d entries", len(view.Players[1].Discard))
	}
}
