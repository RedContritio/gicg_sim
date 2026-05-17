package tests

import (
	"testing"
)

// TestSetPlayerHand_ReplacesContent verifies that SetPlayerHand
// overwrites a player's hand with the given refs, leaving other
// dynamic state (counters, HP, active char, discard) untouched.
func TestSetPlayerHand_ReplacesContent(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// Capture pre-state for invariants
	p0HP := env.HP(0, 0)
	p1HP := env.HP(1, 0)
	p0DeckLen := len(g.Players[0].Deck)
	p1DiscardLen := len(g.Players[1].Discard)
	round := g.Round

	// Pick some card refs from the ruleset to inject (any valid refs).
	// We use 碌碌无为 since it's the filler card and always present.
	filler := env.RT.Cards.ByName["碌碌无为"]
	if filler == nil {
		t.Fatal("filler card 碌碌无为 not found in ruleset")
	}
	fillerRef := filler.Ref

	newHand := []int{fillerRef, fillerRef, fillerRef}
	g.SetPlayerHand(0, newHand)

	// Hand is replaced
	if len(g.Players[0].Hand) != 3 {
		t.Fatalf("expected hand size 3, got %d", len(g.Players[0].Hand))
	}
	for i, card := range g.Players[0].Hand {
		if card.Ref != fillerRef {
			t.Errorf("hand[%d].Ref = %d, want %d", i, card.Ref, fillerRef)
		}
		if card.DrawnAtRound != round {
			t.Errorf("hand[%d].DrawnAtRound = %d, want %d",
				i, card.DrawnAtRound, round)
		}
	}

	// Other state invariants
	if env.HP(0, 0) != p0HP {
		t.Errorf("P0 HP changed: %d → %d", p0HP, env.HP(0, 0))
	}
	if env.HP(1, 0) != p1HP {
		t.Errorf("P1 HP changed: %d → %d", p1HP, env.HP(1, 0))
	}
	if len(g.Players[0].Deck) != p0DeckLen {
		t.Errorf("P0 deck size changed: %d → %d", p0DeckLen, len(g.Players[0].Deck))
	}
	if len(g.Players[1].Discard) != p1DiscardLen {
		t.Errorf("P1 discard size changed")
	}
	// P1 hand untouched
	if len(g.Players[1].Hand) == 0 {
		t.Error("P1 hand unexpectedly empty (should still have round_start draws)")
	}
}

// TestSetPlayerDeck_OrderPreserved verifies that SetPlayerDeck replaces
// the deck with the given refs in order, and that DrawCard pulls from
// the top (refs[0]).
func TestSetPlayerDeck_OrderPreserved(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// Find a couple of distinct card refs to inject
	fillerCard := env.RT.Cards.ByName["碌碌无为"]
	if fillerCard == nil {
		t.Fatal("filler card not found")
	}
	filler := fillerCard.Ref
	var otherRef int
	for name, c := range env.RT.Cards.ByName {
		if name == "碌碌无为" {
			continue
		}
		if env.RT.CardEligibleFor(c, 0) {
			otherRef = c.Ref
			break
		}
	}
	if otherRef == 0 {
		t.Fatalf("could not find a second distinct card ref")
	}

	// Inject a deck: [otherRef, filler, filler]
	newDeck := []int{otherRef, filler, filler}
	g.SetPlayerDeck(0, newDeck)

	if len(g.Players[0].Deck) != 3 {
		t.Fatalf("deck size = %d, want 3", len(g.Players[0].Deck))
	}
	if g.Players[0].Deck[0].Ref != otherRef {
		t.Errorf("deck[0] = %d, want %d (top should be refs[0])",
			g.Players[0].Deck[0].Ref, otherRef)
	}
	if g.Players[0].Deck[0].DrawnAtRound != 0 {
		t.Errorf("freshly injected deck card has DrawnAtRound=%d, want 0",
			g.Players[0].Deck[0].DrawnAtRound)
	}

	// DrawCard pulls from the top
	handBefore := len(g.Players[0].Hand)
	g.DrawCard(0)
	if len(g.Players[0].Hand) != handBefore+1 {
		t.Fatalf("DrawCard: hand size %d → %d, want +1",
			handBefore, len(g.Players[0].Hand))
	}
	drawn := g.Players[0].Hand[len(g.Players[0].Hand)-1]
	if drawn.Ref != otherRef {
		t.Errorf("drew ref %d, want %d (top of injected deck)",
			drawn.Ref, otherRef)
	}
	if len(g.Players[0].Deck) != 2 {
		t.Errorf("deck size after draw = %d, want 2",
			len(g.Players[0].Deck))
	}
}

// TestSetPlayerHand_EmptyRefs verifies that passing an empty slice
// clears the hand. This is the degenerate case for determinization
// when an opponent has 0 hand size.
func TestSetPlayerHand_EmptyRefs(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	g.SetPlayerHand(0, []int{})
	if len(g.Players[0].Hand) != 0 {
		t.Errorf("hand size after SetPlayerHand([]) = %d, want 0",
			len(g.Players[0].Hand))
	}
}

// TestSetPlayerHand_InvalidPlayer verifies that out-of-range player
// indices panic — callers passing 2 or -1 indicate a programmer bug
// and must not be silently absorbed.
func TestSetPlayerHand_InvalidPlayer(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	for _, pi := range []int{-1, 2, 99} {
		func(p int) {
			defer func() {
				if r := recover(); r == nil {
					t.Errorf("SetPlayerHand(%d) did not panic", p)
				}
			}()
			g.SetPlayerHand(p, []int{1, 2, 3})
		}(pi)
	}
}
