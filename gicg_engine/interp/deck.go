package interp

import (
	"fmt"
	"sort"

	engine "gicg_mono/gicg_engine"
)

// DeckPaddingSpec lets callers ask BuildDeck to pad short decks up to a
// fixed length using a specific card name. nil = no padding (deck length
// equals the eligible-card count). Set on the Runtime at game-init time
// from GameConfig; survives Clone/ResetDynamic so deck shape stays
// consistent across the game lifecycle.
type DeckPaddingSpec struct {
	Card       string // padding card name; must be declared in the ruleset
	TargetSize int    // pad up to this length
}

// CardEligibleFor returns true if the card can be included in player pi's deck
// given the bound characters (checks weapon / named-char requirements).
func (rt *Runtime) CardEligibleFor(card *CardRef, pi int) bool {
	if card.RequiresWeapon != 0 {
		found := false
		for ci := 0; ci < MaxChars; ci++ {
			e := rt.Chars.BySlot[pi][ci]
			if e != nil && e.Weapon == card.RequiresWeapon {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	if card.RequiresChar != "" {
		found := false
		for ci := 0; ci < MaxChars; ci++ {
			e := rt.Chars.BySlot[pi][ci]
			if e != nil && e.Name == card.RequiresChar {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}

// BuildDeck fills player pi's deck and shuffles it. Overwrites Deck and
// InitDeck. Two construction paths:
//
// Explicit (rt.ExplicitDecks[pi] != nil): the declared card-name list is
// resolved name→ref in list order (multiset — duplicates allowed). An
// empty (non-nil) list is an error — the implicit path is expressed by
// nil only. Names missing from the loaded ruleset or failing
// CardEligibleFor error out.
//
// Implicit (nil): deck = every declared card eligible for pi, sorted by
// name (UTF-8 byte order). With DeckPadding set, an eligible count above
// TargetSize is an error — the previous silent `eligible[:target]`
// truncation is removed (F4 fail-loud): which cards survived depended on
// byte order of the declared set, so any ruleset change silently
// reshuffled production decks. Callers hitting this declare
// [scenario].deck_0/deck_1 explicitly.
//
// Both paths share padding: with DeckPadding set, a deck longer than
// TargetSize errors, a shorter one is filled with the padding card
// (error if the padding card is not declared).
func (rt *Runtime) BuildDeck(pi int) error {
	var deck []int
	var err error
	if rt.ExplicitDecks[pi] != nil {
		deck, err = rt.resolveExplicitDeck(pi)
	} else {
		deck, err = rt.collectEligibleDeck(pi)
	}
	if err != nil {
		return err
	}

	if rt.DeckPadding != nil && len(deck) < rt.DeckPadding.TargetSize {
		padCard := rt.Cards.ByName[rt.DeckPadding.Card]
		if padCard == nil {
			return fmt.Errorf(
				"deck player %d: %d/%d cards and padding card %q is not declared in the ruleset",
				pi, len(deck), rt.DeckPadding.TargetSize, rt.DeckPadding.Card)
		}
		for len(deck) < rt.DeckPadding.TargetSize {
			deck = append(deck, padCard.Ref)
		}
	}

	// review D.5: use per-player DeckRngs so daemon eval can control
	// "team 同 hand-draw 不同" ablation independently from dice/obs seeds.
	// Fallback to general Rng if DeckRngs not initialized (legacy ckpt
	// load path before ResetDynamicState had run).
	rng := rt.Game.DeckRngs[pi]
	if rng == nil {
		rng = rt.Game.Rng
	}
	for i := len(deck) - 1; i > 0; i-- {
		j := rng.Intn(i + 1)
		deck[i], deck[j] = deck[j], deck[i]
	}

	p := &rt.Game.Players[pi]
	p.Deck = p.Deck[:0]
	for _, ref := range deck {
		// DrawnAtRound 0 = "in deck since game start"; gets overwritten
		// to the actual draw round when DrawCard moves it to the hand.
		p.Deck = append(p.Deck, engine.CardInst{Ref: ref, DrawnAtRound: 0})
	}
	p.InitDeck = append([]engine.CardInst(nil), p.Deck...)
	return nil
}

// resolveExplicitDeck maps rt.ExplicitDecks[pi] card names to refs,
// preserving list order. All missing / ineligible names are collected
// before erroring so one fix round surfaces the full problem.
func (rt *Runtime) resolveExplicitDeck(pi int) ([]int, error) {
	names := rt.ExplicitDecks[pi]
	if len(names) == 0 {
		return nil, fmt.Errorf(
			"deck player %d: explicit deck is empty — declare at least one card, or omit the deck for the implicit path",
			pi)
	}
	if rt.DeckPadding != nil && len(names) > rt.DeckPadding.TargetSize {
		return nil, fmt.Errorf(
			"deck player %d: explicit deck has %d cards, exceeds deck_padding.target_size=%d",
			pi, len(names), rt.DeckPadding.TargetSize)
	}
	deck := make([]int, 0, len(names))
	var missing, ineligible []string
	for _, n := range names {
		card := rt.Cards.ByName[n]
		if card == nil {
			missing = append(missing, n)
			continue
		}
		if !rt.CardEligibleFor(card, pi) {
			ineligible = append(ineligible, n)
			continue
		}
		deck = append(deck, card.Ref)
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf(
			"deck player %d: cards not declared in the ruleset: %v — add them to card_pool/pool, or they were excluded at load",
			pi, missing)
	}
	if len(ineligible) > 0 {
		return nil, fmt.Errorf(
			"deck player %d: cards fail eligibility (weapon / named-char requirement) for this team: %v",
			pi, ineligible)
	}
	return deck, nil
}

// collectEligibleDeck builds the implicit deck: every declared card
// eligible for pi, sorted by name. The padding card is excluded here
// (it only enters via the padding fill in BuildDeck). Errors when the
// eligible count exceeds DeckPadding.TargetSize — see BuildDeck doc.
func (rt *Runtime) collectEligibleDeck(pi int) ([]int, error) {
	paddingName := ""
	if rt.DeckPadding != nil {
		paddingName = rt.DeckPadding.Card
	}

	names := make([]string, 0, len(rt.Cards.ByName))
	for n := range rt.Cards.ByName {
		names = append(names, n)
	}
	sort.Strings(names)

	var deck []int
	var eligibleNames []string
	for _, n := range names {
		if paddingName != "" && n == paddingName {
			continue
		}
		card := rt.Cards.ByName[n]
		if rt.CardEligibleFor(card, pi) {
			deck = append(deck, card.Ref)
			eligibleNames = append(eligibleNames, n)
		}
	}

	if rt.DeckPadding != nil && len(deck) > rt.DeckPadding.TargetSize {
		target := rt.DeckPadding.TargetSize
		return nil, fmt.Errorf(
			"deck player %d: %d eligible cards exceed deck_padding.target_size=%d and no explicit deck is declared — "+
				"silent truncation removed; declare [scenario].deck_%d listing exactly the cards to play "+
				"(cards that would have been truncated: %v)",
			pi, len(deck), target, pi, eligibleNames[target:])
	}
	return deck, nil
}
