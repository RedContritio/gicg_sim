package record

import (
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// Role identifies a counter's semantic function. Display names come from
// g.CounterNames (set by DSL); roles are stable, internal, English.
type Role int

const (
	RoleNone Role = iota
	RoleHP
	RoleEnergy
	RoleAlive
	RoleActive
	RoleAliveCount
	RoleRoundNum
	RoleFirstPlayer
)

// RoleMap maps counter IDs to their semantic role. Built once per Export/
// Verify/Load call from the Runtime's char registry and well-known counter
// entries. Counters without a known role return RoleNone.
type RoleMap map[int]Role

func buildRoleMap(rt *interp.Runtime) RoleMap {
	m := make(RoleMap)

	// Char counters via BySlot refs. Using ByName here would miss counter
	// IDs in mirror matches — the template entry in ByName has -1
	// HP/Energy/Alive/Active counter IDs, because per-slot counter IDs
	// live only on the slot entries (populated by bind_char). Iterating
	// BySlot is the source of truth for per-slot counter identity.
	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < interp.MaxChars; ci++ {
			entry := rt.Chars.BySlot[pi][ci]
			if entry == nil {
				continue
			}
			if entry.HPCounterID >= 0 {
				m[entry.HPCounterID] = RoleHP
			}
			if entry.EnergyCounterID >= 0 {
				m[entry.EnergyCounterID] = RoleEnergy
			}
			if entry.AliveCounterID >= 0 {
				m[entry.AliveCounterID] = RoleAlive
			}
			if entry.ActiveCounterID >= 0 {
				m[entry.ActiveCounterID] = RoleActive
			}
		}
	}

	// Well-known player/global counters by stable internal name
	tag := func(name string, r Role) {
		if e, ok := rt.Counters.Entries[name]; ok {
			for _, id := range e.CounterIDs {
				m[id] = r
			}
		}
	}
	tag(interp.CounterAliveCount, RoleAliveCount)
	tag(interp.CounterRoundNum, RoleRoundNum)
	tag(interp.CounterFirstPlayer, RoleFirstPlayer)

	return m
}

// isCharCounter returns true if counter id is owned by char (p, c).
func isCharCounter(g *engine.Game, id, p, c int) bool {
	m := g.GetCounterChar(id)
	return m[0] == p && m[1] == c
}

// isPlayerCounter returns true if counter id is player-scope for player p.
func isPlayerCounter(g *engine.Game, id, p int) bool {
	m := g.GetCounterChar(id)
	return m[0] == p && m[1] == -1
}
