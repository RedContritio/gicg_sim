package engine

import (
	"fmt"
	"math/rand"
)

// Per-game shuffle permutations (InitShuffle) and general state
// accessor / setter helpers used by the capi and DSL layers.

// --- Shuffle ---

// identityPerm returns the identity permutation [0, 1, ..., n-1].
// Used by InitShuffle when the corresponding shuffle toggle is off,
// so downstream obs code can apply the (now identity) permutation
// unconditionally without branching.
func identityPerm(n int) []int {
	p := make([]int, n)
	for i := range p {
		p[i] = i
	}
	return p
}

func (g *Game) InitShuffle(rng *rand.Rand) {
	n := len(g.Counters)

	switch {
	case !g.Obs.ShuffleCounters && len(g.StructuralSids) > 0:
		// Structural sids still pin canonical positions, but the mechanical
		// counters go into sids K..n-1 in engine-declaration order (no
		// shuffle). Not a realistic training mode — keeps the test-only
		// "identity shuffle + structural pin" case well-defined.
		K := len(g.StructuralSids)
		perm := make([]int, n)
		pinned := make(map[int]bool, K)
		for sid, cid := range g.StructuralSids {
			perm[sid] = cid
			pinned[cid] = true
		}
		next := K
		for id := 0; id < n; id++ {
			if !pinned[id] {
				perm[next] = id
				next++
			}
		}
		g.CounterPerm = perm
	case !g.Obs.ShuffleCounters:
		g.CounterPerm = identityPerm(n)
	case len(g.StructuralSids) > 0:
		// Pin structural counter IDs to sids 0..K-1 in canonical order
		// (set by BuildStructuralCounterIDs). Shuffle the remaining
		// (mechanical) counter IDs across sids K..n-1 so the network
		// still can't learn stable positions for DSL-inferable state.
		K := len(g.StructuralSids)
		perm := make([]int, n)
		pinned := make(map[int]bool, K)
		for sid, cid := range g.StructuralSids {
			perm[sid] = cid
			pinned[cid] = true
		}
		remaining := make([]int, 0, n-K)
		for id := 0; id < n; id++ {
			if !pinned[id] {
				remaining = append(remaining, id)
			}
		}
		rng.Shuffle(len(remaining), func(i, j int) {
			remaining[i], remaining[j] = remaining[j], remaining[i]
		})
		for i, cid := range remaining {
			perm[K+i] = cid
		}
		g.CounterPerm = perm
	default:
		g.CounterPerm = rng.Perm(n)
	}

	totalHooks := g.Hooks.nextID
	if g.Obs.ShuffleHooks {
		g.HookPerm = rng.Perm(totalHooks)
	} else {
		g.HookPerm = identityPerm(totalHooks)
	}

	if g.Obs.ShuffleCards {
		g.CardPerm = rng.Perm(ObsMaxCardTypes)
	} else {
		g.CardPerm = identityPerm(ObsMaxCardTypes)
	}

	// SkillSlotPerm: per (player, char) independent permutation of
	// [0, ObsMaxSkillsPerChar). Without this, physical slot s in the
	// char-skill region would always hold the s-th declared skill of
	// that char — stable across games and across mirror sides. The
	// network could then memorize "slot 0 of 赤蝶 = 2 physical damage"
	// and skip reading hook tokens. Independent per-(p,c) shuffle
	// forces the gather path + hook encoder to carry the semantics.
	skillPerm := make([][][]int, 2)
	for pi := 0; pi < 2; pi++ {
		skillPerm[pi] = make([][]int, ObsMaxChars)
		for ci := 0; ci < ObsMaxChars; ci++ {
			if g.Obs.ShuffleSkillSlots {
				skillPerm[pi][ci] = rng.Perm(ObsMaxSkillsPerChar)
			} else {
				skillPerm[pi][ci] = identityPerm(ObsMaxSkillsPerChar)
			}
		}
	}
	g.SkillSlotPerm = skillPerm
}

func (g *Game) GetState() []float32 {
	out := make([]float32, 0, len(g.Counters)*3)
	perm := g.CounterPerm
	if len(perm) != len(g.Counters) {
		perm = make([]int, len(g.Counters))
		for i := range perm {
			perm[i] = i
		}
	}
	for _, idx := range perm {
		c := g.Counters[idx]
		out = append(out, float32(c.Value), float32(c.Min), float32(c.Max))
	}
	return out
}

// --- 公开辅助 ---

// SetAlive 供 DSL (death.lua) 调用
func (g *Game) SetAlive(playerIdx, charIdx int, alive bool) {
	g.Players[playerIdx].Chars[charIdx].Alive = alive
	if !alive {
		// Credit kill to the opponent, death to the victim. Kills /
		// Deaths are "this step" counters that Python-side code may
		// reset between decisions; Total* mirror them as a running
		// episode tally that doesn't get touched by per-step resets.
		killer := 1 - playerIdx
		g.RewardAccum[killer].Kills++
		g.RewardAccum[killer].TotalKills++
		g.RewardAccum[playerIdx].Deaths++
		g.RewardAccum[playerIdx].TotalDeaths++
		if g.Log != nil {
			g.Log.Append(g, "death", playerIdx, charIdx, nil)
		}
		g.checkWin()
	}
}

// DrawCard 为玩家抽一张牌
func (g *Game) DrawCard(playerIdx int) {
	p := &g.Players[playerIdx]
	if len(p.Deck) == 0 {
		return
	}
	card := p.Deck[0]
	if len(p.Hand) >= 10 {
		p.Deck = p.Deck[1:]
		return
	}
	// Stamp the round at which this card became "held" so reward shaping
	// can compute decay from time-in-hand. Initial deck cards have
	// DrawnAtRound = 0 from BuildDeck; this overwrites with the real draw
	// round when they actually enter the hand.
	card.DrawnAtRound = g.Round
	p.Hand = append(p.Hand, card)
	p.Deck = p.Deck[1:]
	if g.Log != nil {
		g.Log.Append(g, "hand_add", playerIdx, -1, map[string]interface{}{
			"card_ref": card.Ref,
			"from":     "deck",
		})
	}
}

// ActingPlayer returns the player currently owed a decision. Under
// normal play this is g.Turn, but when a forced switch is pending
// (after a char death) it's the victim player who must pick the
// replacement char, not the attacker whose action triggered the death.
//
// MCTS must use this (not g.Turn) as node.turn so that value backup
// and PUCT Q-flipping are correct. g.Turn itself is not mutated by
// pending state because other engine code still relies on it meaning
// "whose global turn is it" — ActingPlayer is the decision-maker
// overlay.
func (g *Game) ActingPlayer() int {
	if g.PendingAction != nil {
		return g.PendingAction.PlayerIdx
	}
	return g.Turn
}

// HasPending reports whether the engine is currently in a pending
// state — either a pending card-target (after a target-requiring card
// was played) or a pending forced-switch (after a char death). Python
// callers use this to decide whether to route the next step to Step
// vs StepTarget, eliminating the need for a local _pending_target flag
// that would have to be tracked through snapshot / restore.
func (g *Game) HasPending() bool {
	return g.PendingAction != nil || g.PendingCardTarget != nil
}

// SetPlayerHand overwrites player pi's hand with the given refs.
// Each ref becomes a new CardInst with DrawnAtRound stamped to the
// current round. Intended for IS-MCTS determinization: the sampler
// generates a hypothetical opponent hand and injects it into a
// cloned engine before rolling forward.
//
// Panics on out-of-range player index — that's a programmer bug.
// Caller is responsible for ref validity: invalid refs will still
// be inserted, and later play_card paths will observe them as
// unknown cards (ref validation is a DSL-level concern).
func (g *Game) SetPlayerHand(playerIdx int, refs []int) {
	if playerIdx < 0 || playerIdx > 1 {
		panic(fmt.Errorf("SetPlayerHand: playerIdx=%d out of range [0,1]", playerIdx))
	}
	p := &g.Players[playerIdx]
	p.Hand = p.Hand[:0]
	for _, ref := range refs {
		p.Hand = append(p.Hand, CardInst{
			Ref:          ref,
			DrawnAtRound: g.Round,
		})
	}
}

// SetPlayerDeck overwrites player pi's deck with the given refs in
// order. refs[0] is the top of the deck (next to be drawn). Each ref
// becomes a new CardInst with DrawnAtRound=0 (consistent with
// BuildDeck's initial-deck semantics). Intended for IS-MCTS
// determinization.
//
// Panics on out-of-range player index — that's a programmer bug.
func (g *Game) SetPlayerDeck(playerIdx int, refs []int) {
	if playerIdx < 0 || playerIdx > 1 {
		panic(fmt.Errorf("SetPlayerDeck: playerIdx=%d out of range [0,1]", playerIdx))
	}
	p := &g.Players[playerIdx]
	p.Deck = p.Deck[:0]
	for _, ref := range refs {
		p.Deck = append(p.Deck, CardInst{
			Ref:          ref,
			DrawnAtRound: 0,
		})
	}
}

// SetWinner 供 DSL (timeout.lua) 调用
func (g *Game) SetWinner(winner int) {
	g.Winner = winner
	g.Phase = PhaseGameOver
	if g.Log != nil {
		g.Log.Append(g, "winner", -1, -1, map[string]interface{}{"winner": winner})
	}
}

// checkWin 检查是否有一方全灭
func (g *Game) checkWin() {
	p0Dead := g.checkAllDead(0)
	p1Dead := g.checkAllDead(1)
	if p0Dead && p1Dead {
		g.SetWinner(2)
	} else if p0Dead {
		g.SetWinner(1)
	} else if p1Dead {
		g.SetWinner(0)
	}
}

func (g *Game) checkAllDead(playerIdx int) bool {
	for _, ch := range g.Players[playerIdx].Chars {
		if ch.Alive {
			return false
		}
	}
	return true
}
