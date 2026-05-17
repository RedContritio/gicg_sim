package interp

import (
	engine "gicg_mono/gicg_engine"
)

// StructuralCount is the number of counter sids the network sees as
// "structural" — fixed-meaning positions that don't get shuffled per
// game. The distinction: structural counters are ones no DSL hook body
// can describe (HP/energy/alive/active/dice/alive_count). Their
// per-game semantics is stable, so they get canonical sids. Everything
// else is DSL-mechanical (shields, buffs, summons, attachments) and
// stays shuffled so the network can't memorize per-name behavior.
//
// Layout (length = StructuralCount = 2*MaxChars*4 + 2*8 + 2):
// Per-char block of 4 (HP, Energy, Alive, Active) iterated over
// (P0 c0..c5, P1 c0..c5) so each char's properties are contiguous.
//
//	sid 0..3:                         P0 c0 (HP, Energy, Alive, Active)
//	sid 4..7:                         P0 c1 (HP, Energy, Alive, Active)
//	... (12 char blocks × 4 = 48 sids)
//	(8*MaxChars)..(8*MaxChars+7):     P0 dice × 8 (fire..omni)
//	(8*MaxChars+8)..(8*MaxChars+15):  P1 dice × 8
//	(8*MaxChars+16), (8*MaxChars+17): P0 alive_count, P1 alive_count
const StructuralCount = 2*MaxChars*4 + 2*8 + 2

// Canonical dice order — must match data/system/dice.lua counter names.
var structuralDiceNames = []string{
	"dice_fire", "dice_ice", "dice_water", "dice_electro",
	"dice_geo", "dice_anemo", "dice_dendro", "dice_omni",
}

// BuildStructuralCounterIDs returns a []int of length StructuralCount
// giving the counter IDs to pin at sids 0..K-1 (canonical order above).
// Creates phantom counters (value=0, min=0, max=0) for unbound char
// slots and for any missing named counters so the sid layout is stable
// across team_size configurations — sid 5 always means "HP of P0 c5"
// whether or not that slot is actually bound.
//
// Must be called after all bind_char calls complete and before
// InitShuffle so the pinned IDs are well-defined.
func (rt *Runtime) BuildStructuralCounterIDs(g *engine.Game) []int {
	ids := make([]int, 0, StructuralCount)

	// Per-char block of (HP, Energy, Alive, Active) iterated over
	// (P0 c0..c5, P1 c0..c5). Each char's 4 properties are contiguous
	// so their sids share a neighborhood in sid_embed.
	charGetters := []func(*CharEntry) int{
		func(e *CharEntry) int { return e.HPCounterID },
		func(e *CharEntry) int { return e.EnergyCounterID },
		func(e *CharEntry) int { return e.AliveCounterID },
		func(e *CharEntry) int { return e.ActiveCounterID },
	}
	for p := 0; p < 2; p++ {
		for c := 0; c < MaxChars; c++ {
			for _, getter := range charGetters {
				cid := -1
				if entry := rt.Chars.BySlot[p][c]; entry != nil {
					cid = getter(entry)
				}
				if cid < 0 {
					cid = g.CreateCounter(0, 0, 0)
					g.RegisterCounterChar(cid, p, c)
				}
				ids = append(ids, cid)
			}
		}
	}

	// Dice × 8 elements per player (PerPlayer scope — always allocated 2 IDs
	// when dice.lua loads). Phantom only as a safety fallback.
	for p := 0; p < 2; p++ {
		for _, name := range structuralDiceNames {
			cid := -1
			if entry, ok := rt.Counters.Entries[name]; ok && p < len(entry.CounterIDs) {
				cid = entry.CounterIDs[p]
			}
			if cid < 0 {
				cid = g.CreateCounter(0, 0, 0)
				g.RegisterCounterChar(cid, p, -1)
			}
			ids = append(ids, cid)
		}
	}

	// alive_count per player (PerPlayer scope).
	for p := 0; p < 2; p++ {
		cid := -1
		if entry, ok := rt.Counters.Entries[CounterAliveCount]; ok && p < len(entry.CounterIDs) {
			cid = entry.CounterIDs[p]
		}
		if cid < 0 {
			cid = g.CreateCounter(0, 0, 0)
			g.RegisterCounterChar(cid, p, -1)
		}
		ids = append(ids, cid)
	}

	return ids
}
