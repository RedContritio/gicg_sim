package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Ruleset holds the static, immutable state produced by loading DSL files:
// the interpreter (parse machinery), and the counter / char / skill / card
// registries. A single Ruleset is shared by any number of concurrent
// Runtime instances that play games against the same rules.
//
// A Ruleset is populated once by the DSL loader and never mutated afterward.
// Runtime instances read from it freely; multiple Runtimes can operate in
// parallel without synchronization because Ruleset is read-only.
type Ruleset struct {
	Interp   *Interpreter
	Counters *CounterRegistry
	Chars    *CharRegistry
	Skills   *SkillRegistry
	Cards    *CardRegistry

	// DiceCounterIDs caches the 16 dice counter IDs (8 colors × 2 players)
	// resolved from the PerPlayer counters declared in data/system/dice.lua.
	// [player][color] → counter ID in Game.Counters, or -1 if dice system
	// not loaded. Populated by BuildDiceIndex() after DSL load; read by
	// Runtime.RollDice / Runtime.ClearDice / Runtime.GetDice.
	DiceCounterIDs [2][engine.DiceColorCount]int
	diceIndexBuilt bool
}

// DiceCounterNames is the canonical ordered list of dice counter
// names that must be declared in data/system/dice.lua. Order matches
// engine.DiceColor* constants.
var DiceCounterNames = [engine.DiceColorCount]string{
	"dice_fire",    // DiceColorFire = 0
	"dice_ice",     // DiceColorIce = 1
	"dice_water",   // DiceColorWater = 2
	"dice_electro", // DiceColorElectro = 3
	"dice_geo",     // DiceColorGeo = 4
	"dice_anemo",   // DiceColorAnemo = 5
	"dice_dendro",  // DiceColorDendro = 6
	"dice_omni",    // DiceColorOmni = 7
}

// NewRuleset creates an empty ruleset ready to be populated by DSL loading.
func NewRuleset() *Ruleset {
	rs := &Ruleset{
		Interp:   NewInterpreter(),
		Counters: NewCounterRegistry(),
		Chars:    NewCharRegistry(),
		Skills:   NewSkillRegistry(),
		Cards:    NewCardRegistry(),
	}
	for pi := range rs.DiceCounterIDs {
		for ci := range rs.DiceCounterIDs[pi] {
			rs.DiceCounterIDs[pi][ci] = -1
		}
	}
	return rs
}

// BuildDiceIndex resolves the 8 canonical dice counter names into
// concrete counter IDs. Must be called after DSL loading completes
// (data/system/dice.lua must have run). Safe to call multiple times;
// subsequent calls refresh the cache.
//
// Panics if any of the 8 dice counters is missing or under-declared
// (< 2 players registered). The engine no longer supports running
// without a dice system — every ruleset must load system/dice.lua.
func (rs *Ruleset) BuildDiceIndex() {
	for colorIdx, name := range DiceCounterNames {
		entry := rs.Counters.Entries[name]
		if entry == nil {
			panic(fmt.Errorf(
				"BuildDiceIndex: dice counter %q not declared "+
					"(is system/dice.lua loaded?)", name))
		}
		if len(entry.CounterIDs) < 2 {
			panic(fmt.Errorf(
				"BuildDiceIndex: dice counter %q has %d player slots, want 2",
				name, len(entry.CounterIDs)))
		}
		rs.DiceCounterIDs[0][colorIdx] = entry.CounterIDs[0]
		rs.DiceCounterIDs[1][colorIdx] = entry.CounterIDs[1]
	}
	rs.diceIndexBuilt = true
}

// DiceIndexBuilt reports whether BuildDiceIndex has been called.
// Runtime.RollDice uses this to lazily trigger a build if the caller
// hasn't explicitly finalized the load.
func (rs *Ruleset) DiceIndexBuilt() bool {
	return rs.diceIndexBuilt
}
