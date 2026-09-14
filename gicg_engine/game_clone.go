package engine

// DeepCopy returns an independent simulation at a decision boundary. Definitions
// are shared, while all gameplay state is copied by the same path as pooled
// snapshots. Extra and Log are external attachments; Runtime.Clone rebinds Extra.
func (g *Game) DeepCopy() *Game {
	snap := g.SnapshotPooled()
	defer ReleaseSnap(snap)
	clone := *g
	// Empty scratch slices can retain backing storage. Sharing that capacity
	// lets independent clones overwrite each other's next event frame.
	clone.eventStack = nil
	clone.damageLogStack = nil
	clone.depth = 0
	clone.executing = nil
	clone.Buffs = nil
	clone.Counters = make([]Counter, len(g.Counters))
	clone.Players = [2]PlayerState{}
	for pi := range clone.Players {
		clone.Players[pi].Chars = append([]CharInfo(nil), g.Players[pi].Chars...)
	}
	clone.PendingAction = nil
	clone.PendingCardTarget = nil
	clone.PendingDice = nil
	clone.RecentDamageEvents = nil
	clone.Rng = nil
	clone.DeckRngs = [2]*Random{}
	clone.Extra = nil
	clone.Log = nil
	clone.RestoreFromSnap(snap)
	return &clone
}

// RestoreFrom restores the exact gameplay and random state without modifying
// snap. Definition identity must match; diagnostics and Extra stay attached.
func (g *Game) RestoreFrom(snap *Game) {
	state := snap.SnapshotPooled()
	defer ReleaseSnap(state)
	g.RestoreFromSnap(state)
}

// ResetDynamicState restores all dynamic per-game state in place. Counter
// values are reset to Init (bypassing hooks), CharInfo.Alive flags are
// reset to true, hand/deck/discard cleared, phase/round/turn reset, RNG
// re-seeded, and the event log replaced if present.
//
// Static identity (Hooks registry, name maps, CounterPerm, HookPerm) is
// preserved. The interpreter Runtime that wraps this Game is responsible
// for re-firing spawn hooks and re-building decks via Runtime.ResetDynamic.
func (g *Game) ResetDynamicState(seed int64) {
	g.Failure = nil
	g.Buffs = nil
	g.BuffSerial = 0
	g.resume = nil
	g.executing = nil
	for i := range g.Counters {
		g.Counters[i].Value = g.Counters[i].Init
	}
	for pi := 0; pi < 2; pi++ {
		p := &g.Players[pi]
		for ci := range p.Chars {
			p.Chars[ci].Alive = true
			p.Chars[ci].SpecialtyCardRef = -1
		}
		p.ActiveChar = -1
		p.DeclaredEnd = false
		p.Hand = p.Hand[:0]
		p.Deck = p.Deck[:0]
		p.Discard = p.Discard[:0]
		p.Supports = p.Supports[:0]
		p.InitDeck = nil
	}
	g.Phase = PhaseSelectActive
	g.Round = 0
	g.Turn = 0
	g.FirstEnd = -1
	g.Winner = -1
	g.DicePaid = [2][DiceColorCount]int{}     // zero payment history
	g.DiceTunedOut = [2][DiceColorCount]int{} // zero tune-out history
	g.DiceTunedIn = [2][DiceColorCount]int{}  // zero tune-in history
	g.RewardAccum = [2]RewardEvents{}         // fresh episode — zero all 14 signals
	g.Preparing = [2]int{}
	g.PendingReactionKind = ReactionNone
	g.PendingAction = nil
	g.PendingCardTarget = nil
	g.PendingDice = nil
	g.eventStack = nil
	g.depth = 0
	// ADR-0019 §B.3 / §B.2 — clear damage history on episode reset
	g.RecentDamageEvents = nil
	g.damageLogStack = nil
	if g.Log != nil {
		g.Log = NewEventLog()
	}
	g.Rng = NewRandom(seed)
	g.BaseSeed = seed
	// review D.5: deck RNGs init from same seed by default (backward compat
	// with single-seed callers). ResetDynamicStateWithSeeds allows the eval
	// path to override these independently.
	g.DeckSeeds = [2]int64{seed, seed}
	g.DeckRngs = [2]*Random{
		NewRandom(seed),
		NewRandom(seed),
	}
}

// ResetDynamicStateWithSeeds — D.5 review extension: 3-axis seed reset.
// diceSeed controls Rng (dice rolls + DSL random_non_active + obs perm
// via InitShuffle); deckSeeds[0/1] independently seed the per-player
// deck shuffle RNGs. Backward compat: ResetDynamicState(seed) routes
// here as ResetDynamicStateWithSeeds(seed, [seed, seed]) so existing
// single-seed callers produce identical deck shuffles as before.
func (g *Game) ResetDynamicStateWithSeeds(diceSeed int64, deckSeeds [2]int64) {
	g.ResetDynamicState(diceSeed)
	g.DeckSeeds = deckSeeds
	g.DeckRngs = [2]*Random{
		NewRandom(deckSeeds[0]),
		NewRandom(deckSeeds[1]),
	}
}

// Snapshot captures the current game state.
func (g *Game) Snapshot() *StateSnapshot {
	snap := &StateSnapshot{
		Round:    g.Round,
		Turn:     g.Turn,
		Phase:    g.Phase,
		Counters: make([]int, len(g.Counters)),
	}
	for i, c := range g.Counters {
		snap.Counters[i] = c.Value
	}
	for pi := 0; pi < 2; pi++ {
		snap.ActiveChars[pi] = g.Players[pi].ActiveChar
		for _, card := range g.Players[pi].Hand {
			snap.Hands[pi] = append(snap.Hands[pi], card.Ref)
		}
		for _, card := range g.Players[pi].Deck {
			snap.Decks[pi] = append(snap.Decks[pi], card.Ref)
		}
		for _, ch := range g.Players[pi].Chars {
			snap.Alive[pi] = append(snap.Alive[pi], ch.Alive)
		}
	}
	return snap
}
