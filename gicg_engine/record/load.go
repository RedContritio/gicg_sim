package record

import (
	"errors"
	"fmt"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// Load overwrites rt's game state to match the start of rec.Rounds[atRound-1].
// The game must already be initialized (chars bound, cards/counters declared).
// After Load, the game is left in PhaseRoundStart — the next Step or
// GetLegalActions call will advance into the round by firing round_start hooks.
func Load(rt *interp.Runtime, rec *Record, atRound int) error {
	return load(rt, rec, atRound, false)
}

func load(rt *interp.Runtime, rec *Record, atRound int, allowLegacyFallback bool) error {
	if rec == nil {
		return fmt.Errorf("nil record")
	}
	if !rt.Game.IsQuiescent() {
		return fmt.Errorf("load requires a quiescent boundary")
	}
	tmp := rt.Clone()
	candidate := tmp.Game
	if err := loadInto(tmp, rec, atRound, allowLegacyFallback); err != nil {
		return err
	}
	rt.Game.RestoreFrom(candidate)
	rt.Game.MaxRounds = candidate.MaxRounds
	rt.Game.FixDice = append([]int(nil), candidate.FixDice...)
	return nil
}

func loadInto(rt *interp.Runtime, rec *Record, atRound int, allowLegacyFallback bool) error {
	if rec.Config != nil {
		if err := rec.Config.validate(); err != nil {
			return err
		}
	}
	if atRound < 1 || atRound > len(rec.Rounds) {
		return fmt.Errorf("round %d out of range [1, %d]", atRound, len(rec.Rounds))
	}
	state := rec.Rounds[atRound-1].Start
	if state == nil {
		return fmt.Errorf("round %d has no start state", atRound)
	}
	g := rt.Game
	if state.Checkpoint != nil {
		// Load's private candidate owns its random/configuration state.
		if err := g.RestoreCheckpoint(state.Checkpoint); err != nil {
			if !allowLegacyFallback || !errors.Is(err, engine.ErrCheckpointIncompatible) {
				return err
			}
			seed := int64(0)
			if rec.Config != nil {
				seed = rec.Config.BaseSeed
			}
			g.ResetDynamicState(seed)
			g.MaxRounds = 0
			g.FixDice = nil
		} else {
			if g.Phase != engine.PhaseRoundStart || g.Round != atRound-1 {
				return fmt.Errorf("checkpoint does not match round %d", atRound)
			}
			if diffs := VerifyState(rt, state); len(diffs) != 0 {
				return fmt.Errorf("checkpoint disagrees with record state: %v", diffs[0])
			}
			return nil
		}
	}
	if state.ActiveChars != nil {
		for pi, ci := range *state.ActiveChars {
			if ci < -1 || ci >= len(g.Players[pi].Chars) {
				return fmt.Errorf("invalid P%d active slot %d", pi, ci)
			}
		}
	}
	if rec.Config != nil {
		g.SetSimulationSeed(rec.Config.BaseSeed)
		g.MaxRounds = rec.Config.MaxRounds
		g.FixDice = append([]int(nil), rec.Config.FixDice...)
	}

	nameToRef := make(map[string]int, len(g.CardNames))
	for ref, name := range g.CardNames {
		nameToRef[name] = ref
	}

	roleMap := buildRoleMap(rt)
	for pi, pe := range [2]PlayerState{state.P0, state.P1} {
		if err := loadPlayer(rt, roleMap, pi, pe, nameToRef); err != nil {
			return fmt.Errorf("P%d: %w", pi, err)
		}
		if state.ActiveChars != nil {
			g.Players[pi].ActiveChar = state.ActiveChars[pi]
		}
	}

	g.Round = atRound - 1
	g.Turn = state.FirstPlayer
	g.FirstEnd = -1
	g.Phase = engine.PhaseRoundStart
	g.Players[0].DeclaredEnd = false
	g.Players[1].DeclaredEnd = false

	// round_num is a Global counter declared by system/round.lua and
	// incremented inside on_round_start. When we auto-advance through
	// NewRound after Load, that hook increments it by 1. Seed it to
	// (atRound-1) so the post-NewRound value equals the target round,
	// matching the in-game invariant "round_num == g.Round after
	// round_start".
	for id, role := range roleMap {
		if role == RoleRoundNum {
			g.Counters[id].Value = atRound - 1
		}
	}
	return nil
}

func loadPlayer(rt *interp.Runtime, roleMap RoleMap, pi int, pe PlayerState, nameToRef map[string]int) error {
	g := rt.Game

	// Player-scope counters (lookup by display name, filtered to player scope)
	for displayName, val := range pe.Counters {
		id := findPlayerCounterByDisplay(g, pi, displayName)
		if id < 0 {
			return fmt.Errorf("unknown player counter %q", displayName)
		}
		g.Counters[id].Value = val
	}

	// Hand
	g.Players[pi].Hand = g.Players[pi].Hand[:0]
	for _, name := range pe.Hand {
		ref, ok := nameToRef[name]
		if !ok {
			return fmt.Errorf("unknown card %q in hand", name)
		}
		g.Players[pi].Hand = append(g.Players[pi].Hand, engine.CardInst{Ref: ref})
	}

	// Deck
	g.Players[pi].Deck = g.Players[pi].Deck[:0]
	for _, name := range pe.Deck {
		ref, ok := nameToRef[name]
		if !ok {
			return fmt.Errorf("unknown card %q in deck", name)
		}
		g.Players[pi].Deck = append(g.Players[pi].Deck, engine.CardInst{Ref: ref})
	}

	// Chars
	activeChar := -1
	for _, cs := range pe.Chars {
		ci := findCharSlot(g, pi, cs.Name)
		if ci < 0 {
			return fmt.Errorf("unknown char %q", cs.Name)
		}

		// Build display_name → id map for this char's counters
		charCounters := make(map[string]int)
		for id, name := range g.CounterNames {
			if isCharCounter(g, id, pi, ci) {
				charCounters[name] = id
			}
		}

		// Apply each expected counter value; track which ids were set so the
		// rest can be reset to init.
		setIDs := make(map[int]bool)
		for expName, expVal := range cs.Counters {
			id, ok := charCounters[expName]
			if !ok {
				return fmt.Errorf("unknown counter %q for char %q", expName, cs.Name)
			}
			g.Counters[id].Value = expVal
			setIDs[id] = true
			// Track active char via the alive/active roles
			if roleMap[id] == RoleActive && expVal > 0 {
				activeChar = ci
			}
			// Mirror CharInfo.Alive from the alive counter
			if roleMap[id] == RoleAlive {
				g.Players[pi].Chars[ci].Alive = expVal > 0
			}
		}
		// Reset other char counters to init
		for _, id := range charCounters {
			if setIDs[id] {
				continue
			}
			g.Counters[id].Value = g.Counters[id].Init
		}
	}
	g.Players[pi].ActiveChar = activeChar
	return nil
}

func findCharSlot(g *engine.Game, pi int, name string) int {
	for ci := range g.Players[pi].Chars {
		if n, ok := g.CharNames[[2]int{pi, ci}]; ok && n == name {
			return ci
		}
	}
	return -1
}
