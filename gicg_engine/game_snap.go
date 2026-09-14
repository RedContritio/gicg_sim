package engine

import (
	"maps"
	"sync"
)

// GameSnap captures gameplay at quiescent decision boundaries. Definitions are
// immutable; hook-registry identity guards restores. Logs and Extra stay attached.
type GameSnap struct {
	Phase                               Phase
	Round, Turn, FirstEnd, Winner       int
	BaseSeed                            int64
	DicePaid, DiceTunedOut, DiceTunedIn [2][DiceColorCount]int
	RewardAccum                         [2]RewardEvents
	Preparing                           [2]int
	PendingReactionKind                 int
	BuffSerial                          uint64
	Buffs                               []BuffInstance
	Counters                            []Counter
	RecentDamageEvents                  []RecentDamageEvent
	Players                             [2]PlayerState
	PendingAction                       *Action
	PendingCardTarget                   *PendingCard
	PendingDice                         *DiceSelection
	Rng                                 *Random
	DeckRngs                            [2]*Random
	DeckSeeds                           [2]int64
	hooks                               *HookRegistry
	resume                              *continuation
}

var snapPool = sync.Pool{New: func() any { return &GameSnap{} }}

func copyAction(a *Action) *Action {
	if a == nil {
		return nil
	}
	copy := *a
	copy.AppliedMods = maps.Clone(a.AppliedMods)
	return &copy
}

func copyPendingCard(p *PendingCard) *PendingCard {
	if p == nil {
		return nil
	}
	copy := *p
	copy.AppliedMods = maps.Clone(p.AppliedMods)
	return &copy
}

func copyPlayer(dst *PlayerState, src *PlayerState) {
	dst.ActiveChar = src.ActiveChar
	dst.DeclaredEnd = src.DeclaredEnd
	dst.Chars = append(dst.Chars[:0], src.Chars...)
	// Skills are immutable after binding; remaining CharInfo fields are values.
	dst.Hand = append(dst.Hand[:0], src.Hand...)
	dst.Deck = append(dst.Deck[:0], src.Deck...)
	dst.Discard = append(dst.Discard[:0], src.Discard...)
	dst.Supports = append(dst.Supports[:0], src.Supports...)
	dst.InitDeck = append(dst.InitDeck[:0], src.InitDeck...)
}

func copyDamageEvents(src []RecentDamageEvent) []RecentDamageEvent {
	if src == nil {
		return nil
	}
	dst := make([]RecentDamageEvent, len(src))
	for i, e := range src {
		dst[i] = e
		dst[i].Modifiers = append([]Modifier(nil), e.Modifiers...)
	}
	return dst
}

func (g *Game) requireQuiescent() {
	g.RequireHealthy()
	if !g.IsQuiescent() {
		panic("snapshot/restore requires a quiescent decision boundary")
	}
}

func (g *Game) IsQuiescent() bool {
	return g.Failure == nil && g.executing == nil && len(g.eventStack) == 0 && len(g.damageLogStack) == 0 && g.depth == 0
}

// CanRestoreFrom lets foreign-function callers reject invalid handles/shapes
// without propagating a Go panic across the C boundary.
func (g *Game) CanRestoreFrom(s *Game) bool {
	if s == nil || !g.IsQuiescent() || !s.IsQuiescent() || g.Hooks != s.Hooks || len(g.Counters) != len(s.Counters) {
		return false
	}
	for pi := range g.Players {
		if len(g.Players[pi].Chars) != len(s.Players[pi].Chars) {
			return false
		}
	}
	return true
}

// SnapshotPooled never advances RNGs. Release once after the final restore.
func (g *Game) SnapshotPooled() *GameSnap {
	g.requireQuiescent()
	s := snapPool.Get().(*GameSnap)
	s.hooks = g.Hooks
	s.resume = g.resume
	s.Phase, s.Round, s.Turn = g.Phase, g.Round, g.Turn
	s.FirstEnd, s.Winner, s.BaseSeed = g.FirstEnd, g.Winner, g.BaseSeed
	s.DicePaid, s.DiceTunedOut, s.DiceTunedIn = g.DicePaid, g.DiceTunedOut, g.DiceTunedIn
	s.RewardAccum, s.Preparing = g.RewardAccum, g.Preparing
	s.PendingReactionKind = g.PendingReactionKind
	s.Counters = append(s.Counters[:0], g.Counters...)
	s.BuffSerial = g.BuffSerial
	s.Buffs = append(s.Buffs[:0], g.Buffs...)
	s.RecentDamageEvents = copyDamageEvents(g.RecentDamageEvents)
	for pi := range g.Players {
		copyPlayer(&s.Players[pi], &g.Players[pi])
	}
	s.PendingAction = copyAction(g.PendingAction)
	s.PendingCardTarget = copyPendingCard(g.PendingCardTarget)
	s.PendingDice = copyDiceSelection(g.PendingDice)
	s.Rng = copyRandom(s.Rng, g.Rng)
	s.DeckSeeds = g.DeckSeeds
	for pi := range g.DeckRngs {
		s.DeckRngs[pi] = copyRandom(s.DeckRngs[pi], g.DeckRngs[pi])
	}
	return s
}

// RestoreFromSnap never consumes or aliases mutable snapshot data. Invalid
// restores fail before mutation. Log and Extra are external attachments.
func (g *Game) RestoreFromSnap(s *GameSnap) {
	g.requireQuiescent()
	if s == nil || s.hooks != g.Hooks || len(s.Counters) != len(g.Counters) {
		panic("restore: incompatible ruleset or counter shape")
	}
	for pi := range g.Players {
		if len(g.Players[pi].Chars) != len(s.Players[pi].Chars) {
			panic("restore: incompatible character shape")
		}
	}
	g.restoreGameplay(s)
}

// Internal restoration at a reconstructed input boundary keeps live execution
// scratch intact. Public callers must use RestoreFromSnap and its validation.
func (g *Game) restoreGameplay(s *GameSnap) {
	g.resume = s.resume
	copy(g.Counters, s.Counters)
	g.BuffSerial = s.BuffSerial
	g.Buffs = append(g.Buffs[:0], s.Buffs...)
	for pi := range g.Players {
		copyPlayer(&g.Players[pi], &s.Players[pi])
	}
	g.Phase, g.Round, g.Turn = s.Phase, s.Round, s.Turn
	g.FirstEnd, g.Winner, g.BaseSeed = s.FirstEnd, s.Winner, s.BaseSeed
	g.DicePaid, g.DiceTunedOut, g.DiceTunedIn = s.DicePaid, s.DiceTunedOut, s.DiceTunedIn
	g.RewardAccum, g.Preparing = s.RewardAccum, s.Preparing
	g.PendingReactionKind = s.PendingReactionKind
	g.PendingAction = copyAction(s.PendingAction)
	g.PendingCardTarget = copyPendingCard(s.PendingCardTarget)
	g.PendingDice = copyDiceSelection(s.PendingDice)
	g.RecentDamageEvents = copyDamageEvents(s.RecentDamageEvents)
	g.Rng = copyRandom(g.Rng, s.Rng)
	g.DeckSeeds = s.DeckSeeds
	for pi := range g.DeckRngs {
		g.DeckRngs[pi] = copyRandom(g.DeckRngs[pi], s.DeckRngs[pi])
	}
}

// ReleaseSnap(nil) is a no-op. Non-nil snapshots must be released once only.
func ReleaseSnap(s *GameSnap) {
	if s == nil {
		return
	}
	s.PendingAction, s.PendingCardTarget = nil, nil
	s.PendingDice = nil
	s.RecentDamageEvents = nil
	s.hooks = nil
	s.resume = nil
	snapPool.Put(s)
}
