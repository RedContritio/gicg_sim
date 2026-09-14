package engine

import (
	"fmt"
)

// BuffDefinition binds generic counter state to immutable rule hooks. No card
// names enter execution. Counter IDs stay internal and are remapped for NN obs.
type BuffDefinition struct {
	CounterID       int
	RuleSources     []string
	DurationID      int
	ProgressID      int
	RemoveOnDeath   bool
	ExpiresRoundEnd bool
	ReplaceOnChange bool
	Summon          bool // DSL summon-zone membership; affects cross-player round order
	Independent     bool
	HookIDs         []int
}

// BuffInstance order IS creation order. Aggregate buffs read their definition's
// counters; independent buffs keep their own value, duration and progress.
type BuffInstance struct {
	ID                        uint64 // lifecycle identity only; never exposed as NN input
	Definition                int
	Independent               bool
	Value, Duration, Progress int
}

func (g *Game) newBuffInstance(definition int) BuffInstance {
	return BuffInstance{ID: g.nextEffectIdentity(), Definition: definition}
}

func (g *Game) nextEffectIdentity() uint64 {
	g.BuffSerial++
	if g.BuffSerial == 0 {
		panic("buff identity overflow")
	}
	return g.BuffSerial
}

func (g *Game) buffByID(id uint64) *BuffInstance {
	for i := range g.Buffs {
		if g.Buffs[i].ID == id {
			return &g.Buffs[i]
		}
	}
	return nil
}

func (g *Game) EnableCounterOrder(id int, replacement bool) {
	if g.Counters[id].BuffIndex >= 0 {
		return
	}
	g.Counters[id].BuffIndex = len(g.BuffDefinitions)
	g.BuffDefinitions = append(g.BuffDefinitions, BuffDefinition{CounterID: id, DurationID: -1, ProgressID: -1, ReplaceOnChange: replacement})
	if g.Counters[id].Value != g.Counters[id].Init {
		g.Buffs = append(g.Buffs, g.newBuffInstance(g.Counters[id].BuffIndex))
	}
}

func (g *Game) updateBuffInstance(id, before int) {
	index := g.Counters[id].BuffIndex
	if index < 0 {
		return
	}
	def := g.BuffDefinitions[index]
	active := g.Counters[id].Value != g.Counters[id].Init
	replace := def.ReplaceOnChange && before != g.Counters[id].Value
	for i, b := range g.Buffs {
		if b.Definition != index {
			continue
		}
		if active && !replace {
			return
		}
		g.Buffs = append(g.Buffs[:i], g.Buffs[i+1:]...)
		break
	}
	if active {
		g.Buffs = append(g.Buffs, g.newBuffInstance(index))
	}
}

func (g *Game) removeCharacterBuffs(player, char int) {
	// Snapshot: writes can remove instances and trigger additional effects.
	for _, b := range append([]BuffInstance(nil), g.Buffs...) {
		d := g.BuffDefinitions[b.Definition]
		if d.RemoveOnDeath && g.GetCounterChar(d.CounterID) == [2]int{player, char} {
			if b.Independent {
				g.RemoveBuff(b.ID)
			} else {
				g.WriteCounter(d.CounterID, OpSet, g.Counters[d.CounterID].Init)
			}
		}
	}
}

func (g *Game) validateBuffState(s *GameSnap) error {
	seen := map[int]bool{}
	identities := map[uint64]bool{}
	for _, b := range s.Buffs {
		if b.ID == 0 || b.ID > s.BuffSerial || identities[b.ID] {
			return fmt.Errorf("invalid buff lifecycle identity")
		}
		identities[b.ID] = true
		if b.Definition < 0 || b.Definition >= len(g.BuffDefinitions) || (!b.Independent && seen[b.Definition]) {
			return fmt.Errorf("invalid/duplicate buff instance")
		}
		if b.Independent != g.BuffDefinitions[b.Definition].Independent {
			return fmt.Errorf("buff storage mode mismatch")
		}
		if b.Independent {
			if b.Progress < 0 || b.Progress > 2147483647 {
				return fmt.Errorf("invalid independent buff progress")
			}
			if !g.BuffDefinitions[b.Definition].Independent || b.Value <= 0 || b.Value > s.Counters[g.BuffDefinitions[b.Definition].CounterID].Max || b.Duration < -1 || b.Duration == 0 {
				return fmt.Errorf("invalid independent buff state")
			}
			continue
		}
		seen[b.Definition] = true
		d := g.BuffDefinitions[b.Definition]
		if s.Counters[d.CounterID].Value == s.Counters[d.CounterID].Init {
			return fmt.Errorf("inactive buff instance")
		}
	}
	for i, d := range g.BuffDefinitions {
		if (s.Counters[d.CounterID].Value != s.Counters[d.CounterID].Init) != seen[i] {
			return fmt.Errorf("buff list/counter mismatch")
		}
	}
	return nil
}
