package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// TestCardWithNoValidTarget_NotOffered is the regression test for a
// PhaseAction-zero-legal-actions deadlock discovered during the
// p0_elo_A phase1_warmup training run (2026-04-14):
//
//  1. Player has 美味烧鸡 (target=own, locked-out by per-char 饱腹
//     counter) in hand.
//  2. Their only own char has already eaten — 饱腹 = 1.
//  3. GetLegalActions's candidate-phase action_check fires with
//     TargetPlayer=FilterAny; the 美味烧鸡 hook early-returns on
//     FilterAny and leaves Playable=true.
//  4. The card enters the candidate list. A random rollout picks it.
//  5. executeCard sets PendingCardTarget and returns StepNeedTarget.
//  6. cardTargetActions iterates concrete targets, every one fails
//     action_check, returns [].
//  7. Next GetLegalActions call hits the PendingCardTarget branch
//     (line ~35 in action.go) and returns the empty target list
//     *without* appending EndTurn.
//  8. Rollout sees 0 legal actions, marks episode truncated, halts.
//
// Fix: in the candidate enumeration, after the existing action_check
// passes, additionally probe cardTargetActions for cards that
// declared NeedTarget. If no concrete target survives, drop the card
// from candidates so it never gets offered in the first place.
//
// This test sets up the exact 1v1 mirror state that triggered the
// deadlock and asserts that GetLegalActions:
//
//	(a) does not list 美味烧鸡, AND
//	(b) returns at least one EndTurn (i.e. is non-empty).
func TestCardWithNoValidTarget_NotOffered(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})
	env.G.Log = engine.NewEventLog()

	// Advance past the initial select-active so we're in PhaseAction.
	for env.G.Phase == engine.PhaseSelectActive {
		env.Step(0)
	}

	// Add 美味烧鸡 to P0's hand so the candidate list will consider it.
	cardEntry, ok := env.RT.Cards.ByName["美味烧鸡"]
	if !ok {
		t.Fatal("card 美味烧鸡 not declared (build issue?)")
	}
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: cardEntry.Ref})

	// Mark the only own char's 饱腹 = 1 so 美味烧鸡's on_action_check
	// would block ANY concrete-target play.
	baoFu, ok := env.RT.CounterEntries()["饱腹"]
	if !ok {
		t.Fatal("counter 饱腹 not declared")
	}
	// PerChar scope: counter ID at p0c0 lives at index 0 of the
	// flat [2 * MaxChars] IDs array (layout: p0c0, p0c1, ..., p1c0, ...).
	pc, ok := baoFu.Ref.(*interp.PerCharProxy)
	if !ok {
		t.Fatalf("expected PerCharProxy for 饱腹, got %T", baoFu.Ref)
	}
	env.G.Counters[pc.IDs[0]].Value = 1

	// Make sure the active player is P0 with enough AP.
	env.G.Turn = 0

	actions := env.G.GetLegalActions()
	if len(actions) == 0 {
		t.Fatal("invariant: GetLegalActions returned 0 actions in PhaseAction — deadlock")
	}

	// 美味烧鸡 must NOT appear among legal cards.
	for _, a := range actions {
		if a.Kind != engine.ActionCard {
			continue
		}
		if a.PlayerIdx != 0 || a.Index >= len(env.G.Players[0].Hand) {
			continue
		}
		ref := env.G.Players[0].Hand[a.Index].Ref
		if ref == cardEntry.Ref {
			t.Errorf("美味烧鸡 still offered as legal even though no own char is a valid target")
		}
	}

	// EndTurn must be present.
	var haveEnd bool
	for _, a := range actions {
		if a.Kind == engine.ActionEndTurn {
			haveEnd = true
			break
		}
	}
	if !haveEnd {
		t.Error("expected EndTurn in legal actions")
	}
}
