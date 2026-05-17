package interp

import (
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

// BuildDeck fills player pi's deck with eligible cards and shuffles it.
// If rt.DeckPadding is non-nil the deck is padded up to TargetSize with
// the named padding card; otherwise the deck length equals the eligible
// count. Overwrites Deck and InitDeck.
func (rt *Runtime) BuildDeck(pi int) {
	var paddingRef int = -1
	var paddingName string
	if rt.DeckPadding != nil {
		paddingName = rt.DeckPadding.Card
	}

	var eligible []int
	names := make([]string, 0, len(rt.Cards.ByName))
	for n := range rt.Cards.ByName {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		card := rt.Cards.ByName[n]
		if paddingName != "" && n == paddingName {
			paddingRef = card.Ref
			continue
		}
		if rt.CardEligibleFor(card, pi) {
			eligible = append(eligible, card.Ref)
		}
	}

	var deck []int
	if rt.DeckPadding != nil {
		target := rt.DeckPadding.TargetSize
		if len(eligible) >= target {
			deck = eligible[:target]
		} else {
			deck = append(deck, eligible...)
			for len(deck) < target && paddingRef >= 0 {
				deck = append(deck, paddingRef)
			}
		}
	} else {
		deck = append(deck, eligible...)
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
}
