package engine

import (
	"math/rand"
)

// DeepCopy returns an independent copy of the game's dynamic state, suitable
// for parallel speculative rollouts. Immutable metadata (Hooks registry,
// SkillNames, CharNames, CounterNames, CardNames, counterCharMap, CounterPerm,
// HookPerm) is shared by pointer aliasing — the engine guarantees these are
// populated once at DSL load time and never mutated thereafter.
//
// The caller is responsible for setting Extra on the returned Game (typically
// pointing to a new interp.Runtime that wraps this clone).
func (g *Game) DeepCopy() *Game {
	clone := &Game{
		// Immutable / shared
		Hooks:               g.Hooks,
		counterCharMap:      g.counterCharMap,
		SkillNames:          g.SkillNames,
		CardNames:           g.CardNames,
		CharNames:           g.CharNames,
		CounterNames:        g.CounterNames,
		CounterPerm:         g.CounterPerm,
		HookPerm:            g.HookPerm,
		CardPerm:            g.CardPerm,
		SkillSlotPerm:       g.SkillSlotPerm,
		CanonicalSkillHooks: g.CanonicalSkillHooks,
		CanonicalCardHooks:  g.CanonicalCardHooks,
		Obs:                 g.Obs,

		// Dynamic scalars
		Phase:        g.Phase,
		Round:        g.Round,
		Turn:         g.Turn,
		FirstEnd:     g.FirstEnd,
		Winner:       g.Winner,
		BaseSeed:     g.BaseSeed,
		DicePaid:     g.DicePaid, // value copy of [2][8]int arrays
		DiceTunedOut: g.DiceTunedOut,
		DiceTunedIn:  g.DiceTunedIn,
		// RewardAccum is a value-copy [2]RewardEvents; the clone's
		// downstream events (e.g. speculative rollouts inside
		// GreedyPlayer depth>=2) accumulate into the clone without
		// polluting the parent. Passing the value at construction
		// time is correct — a later RestoreFrom will overwrite it.
		RewardAccum: g.RewardAccum,
		// MaxRounds / FixDice are static config, set once at GameNew
		// and never mutated — safe to alias FixDice (it's read-only).
		MaxRounds: g.MaxRounds,
		FixDice:   g.FixDice,
		depth:     0, // never carry recursion depth across clone
	}

	// Deep-copy counter values (schemas Min/Max/Init are shared via value copy)
	clone.Counters = make([]Counter, len(g.Counters))
	copy(clone.Counters, g.Counters)

	// ADR-0019 §B.3 — RecentDamageEvents ring buffer (跨 damage 累积,obs encoder
	// 读 → 必须 deep copy 保 clone 与原独立);Modifiers 内嵌 slice 也深拷贝。
	if len(g.RecentDamageEvents) > 0 {
		clone.RecentDamageEvents = make([]RecentDamageEvent, len(g.RecentDamageEvents))
		for i, e := range g.RecentDamageEvents {
			clone.RecentDamageEvents[i] = e
			if len(e.Modifiers) > 0 {
				clone.RecentDamageEvents[i].Modifiers = append([]Modifier(nil), e.Modifiers...)
			}
		}
	}
	// damageLogStack only lives across DealDamage execution; snapshot
	// points are between Step calls (event stack drained) so stack is
	// empty here — no copy needed, leave clone's stack nil.

	// Deep-copy players
	for pi := 0; pi < 2; pi++ {
		src := &g.Players[pi]
		dst := &clone.Players[pi]
		dst.Chars = make([]CharInfo, len(src.Chars))
		for ci, ch := range src.Chars {
			// CharInfo.Skills is populated at bind time and never mutated
			// during play, so we share the slice.
			dst.Chars[ci] = ch
		}
		dst.ActiveChar = src.ActiveChar
		dst.Hand = append([]CardInst(nil), src.Hand...)
		dst.Deck = append([]CardInst(nil), src.Deck...)
		dst.Discard = append([]CardInst(nil), src.Discard...)
		dst.Supports = append([]SupportInst(nil), src.Supports...)
		dst.InitDeck = src.InitDeck // initial deck is immutable
		dst.DeclaredEnd = src.DeclaredEnd
	}

	// Preserve pending state so snapshots taken at decision points that
	// include a pending forced-switch or pending card-target survive the
	// clone. These are POD structs; we deep-copy to keep the snap fully
	// independent from the original's mutation.
	//
	// eventStack is kept nil because all snapshot-worthy points are at
	// Step boundaries where the event stack has been drained — see
	// docs/az/decisions.md D2 and docs/az/mcts_design.md for the contract.
	if g.PendingAction != nil {
		actionCopy := *g.PendingAction
		clone.PendingAction = &actionCopy
	}
	if g.PendingCardTarget != nil {
		targetCopy := *g.PendingCardTarget
		clone.PendingCardTarget = &targetCopy
	}
	clone.eventStack = nil

	// RNG: fork deterministically from current state. math/rand doesn't
	// expose its state portably, so we re-seed from a fresh int64 derived
	// from the current Rng. Callers that need deterministic cloning should
	// pass an explicit seed via a higher-level API.
	if g.Rng != nil {
		clone.Rng = rand.New(rand.NewSource(g.Rng.Int63()))
	}
	// review D.5: deck RNGs also fork-by-int63 — same caveats as Rng.
	clone.DeckSeeds = g.DeckSeeds
	for pi := 0; pi < 2; pi++ {
		if g.DeckRngs[pi] != nil {
			clone.DeckRngs[pi] = rand.New(rand.NewSource(g.DeckRngs[pi].Int63()))
		}
	}

	// Log: clones get a fresh log (don't inherit the original's event history).
	// If the caller wants to record clone play, they can attach a new EventLog.
	clone.Log = nil

	return clone
}

// RestoreFrom copies dynamic state from snap into the receiver, preserving
// static identity (Hooks, Extra, name maps, CounterPerm/HookPerm). Intended
// for use with snapshots taken at quiescent points (between Step calls),
// where the event stack is empty. Counter slices must have matching lengths
// — snapshots from a different ruleset are not supported.
func (g *Game) RestoreFrom(snap *Game) {
	if len(g.Counters) != len(snap.Counters) {
		return
	}
	copy(g.Counters, snap.Counters)
	for pi := 0; pi < 2; pi++ {
		src := &snap.Players[pi]
		dst := &g.Players[pi]
		for ci := range dst.Chars {
			if ci < len(src.Chars) {
				dst.Chars[ci].Alive = src.Chars[ci].Alive
			}
		}
		dst.ActiveChar = src.ActiveChar
		dst.DeclaredEnd = src.DeclaredEnd
		dst.Hand = append(dst.Hand[:0], src.Hand...)
		dst.Deck = append(dst.Deck[:0], src.Deck...)
		dst.Discard = append(dst.Discard[:0], src.Discard...)
	}
	g.Phase = snap.Phase
	g.Round = snap.Round
	g.Turn = snap.Turn
	g.FirstEnd = snap.FirstEnd
	g.Winner = snap.Winner
	g.BaseSeed = snap.BaseSeed
	g.DicePaid = snap.DicePaid
	g.DiceTunedOut = snap.DiceTunedOut
	g.DiceTunedIn = snap.DiceTunedIn
	g.RewardAccum = snap.RewardAccum
	g.PendingAction = snap.PendingAction
	g.PendingCardTarget = snap.PendingCardTarget
	g.eventStack = nil
	g.depth = 0
	// ADR-0019 §B.3 — RecentDamageEvents ring buffer (obs encoder 读 → 必须
	// 跟 snapshot 一致;deep copy + Modifiers 内嵌 slice)
	if len(snap.RecentDamageEvents) > 0 {
		g.RecentDamageEvents = make([]RecentDamageEvent, len(snap.RecentDamageEvents))
		for i, e := range snap.RecentDamageEvents {
			g.RecentDamageEvents[i] = e
			if len(e.Modifiers) > 0 {
				g.RecentDamageEvents[i].Modifiers = append([]Modifier(nil), e.Modifiers...)
			}
		}
	} else {
		g.RecentDamageEvents = nil
	}
	g.damageLogStack = nil // 永远 quiescent point 时为空
	if snap.Rng != nil {
		g.Rng = rand.New(rand.NewSource(snap.Rng.Int63()))
	}
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
	for i := range g.Counters {
		g.Counters[i].Value = g.Counters[i].Init
	}
	for pi := 0; pi < 2; pi++ {
		p := &g.Players[pi]
		for ci := range p.Chars {
			p.Chars[ci].Alive = true
		}
		p.ActiveChar = -1
		p.DeclaredEnd = false
		p.Hand = p.Hand[:0]
		p.Deck = p.Deck[:0]
		p.Discard = p.Discard[:0]
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
	g.PendingAction = nil
	g.PendingCardTarget = nil
	g.eventStack = nil
	g.depth = 0
	// ADR-0019 §B.3 / §B.2 — clear damage history on episode reset
	g.RecentDamageEvents = nil
	g.damageLogStack = nil
	if g.Log != nil {
		g.Log = NewEventLog()
	}
	g.Rng = rand.New(rand.NewSource(seed))
	g.BaseSeed = seed
	// review D.5: deck RNGs init from same seed by default (backward compat
	// with single-seed callers). ResetDynamicStateWithSeeds allows the eval
	// path to override these independently.
	g.DeckSeeds = [2]int64{seed, seed}
	g.DeckRngs = [2]*rand.Rand{
		rand.New(rand.NewSource(seed)),
		rand.New(rand.NewSource(seed)),
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
	g.DeckRngs = [2]*rand.Rand{
		rand.New(rand.NewSource(deckSeeds[0])),
		rand.New(rand.NewSource(deckSeeds[1])),
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
