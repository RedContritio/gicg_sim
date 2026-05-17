package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// checkPlayer panics on an out-of-range player index. Shared by every
// dice API so the "programmer bug" error path is consistent.
func checkPlayer(op string, playerIdx int) {
	if playerIdx < 0 || playerIdx > 1 {
		panic(fmt.Errorf("%s: playerIdx=%d out of range [0,1]", op, playerIdx))
	}
}

// checkColor panics on an out-of-range dice color index.
func checkColor(op string, color int) {
	if color < 0 || color >= engine.DiceColorCount {
		panic(fmt.Errorf("%s: color=%d out of range [0,%d)", op, color, engine.DiceColorCount))
	}
}

// diceSlot returns the counter ID for the given (player, color),
// lazily building the dice index on first use. The index build itself
// panics if any dice counter is missing, so any cid this returns is
// guaranteed to be valid — there is no "missing dice system" escape
// hatch anymore (Phase IV assumes system/dice.lua is always loaded).
func (rt *Runtime) diceSlot(playerIdx, color int) int {
	if !rt.Ruleset.DiceIndexBuilt() {
		rt.Ruleset.BuildDiceIndex()
	}
	return rt.Ruleset.DiceCounterIDs[playerIdx][color]
}

// RollDice rolls n dice for the given player into the dice counter
// pool. Each dice is independently sampled uniformly over the 8 dice
// colors (7 elements + omni). Previous dice in the pool are CLEARED
// before rolling — this matches the "discard at round end, fresh roll
// at round start" rule.
//
// When Game.FixDice is length DiceColorCount, the roll is replaced
// by the fixed per-color counts (n is ignored) — curriculum Stage 0
// uses this to eliminate dice stochasticity. Length 0 / nil keeps the
// random path.
//
// Panics on out-of-range player, missing RNG (when randomizing),
// malformed FixDice, or negative FixDice entries.
func (rt *Runtime) RollDice(playerIdx, n int) {
	checkPlayer("RollDice", playerIdx)
	g := rt.Game
	for c := 0; c < engine.DiceColorCount; c++ {
		g.Counters[rt.diceSlot(playerIdx, c)].Value = 0
	}
	if len(g.FixDice) > 0 {
		if len(g.FixDice) != engine.DiceColorCount {
			panic(fmt.Errorf(
				"RollDice: FixDice length %d, expected %d",
				len(g.FixDice), engine.DiceColorCount,
			))
		}
		for c := 0; c < engine.DiceColorCount; c++ {
			if g.FixDice[c] < 0 {
				panic(fmt.Errorf("RollDice: FixDice[%d]=%d is negative", c, g.FixDice[c]))
			}
			g.Counters[rt.diceSlot(playerIdx, c)].Value = g.FixDice[c]
		}
		return
	}
	if g.Rng == nil {
		panic(fmt.Errorf("RollDice: Game.Rng is nil — initialize before rolling"))
	}
	for i := 0; i < n; i++ {
		colorIdx := g.Rng.Intn(engine.DiceColorCount)
		g.Counters[rt.diceSlot(playerIdx, colorIdx)].Value++
	}
}

// SetPlayerDice overwrites player pi's dice pool with exact per-color
// counts. counts is indexed by DiceColor* (fire=0 … omni=7). All 8
// slots are written — pass 0 for colors you want cleared.
//
// Intended for IS-MCTS determinization: the sampler draws a
// multinomial dice distribution for the opponent and injects it into
// the cloned engine before rolling forward.
//
// Panics on out-of-range player or negative counts.
func (rt *Runtime) SetPlayerDice(playerIdx int, counts [engine.DiceColorCount]int) {
	checkPlayer("SetPlayerDice", playerIdx)
	for c := 0; c < engine.DiceColorCount; c++ {
		if counts[c] < 0 {
			panic(fmt.Errorf(
				"SetPlayerDice: counts[%d]=%d is negative", c, counts[c]))
		}
	}
	g := rt.Game
	for c := 0; c < engine.DiceColorCount; c++ {
		g.Counters[rt.diceSlot(playerIdx, c)].Value = counts[c]
	}
}

// ClearDice zeroes all 8 dice counters for the given player. Used at
// round end to discard unused dice before next round's fresh roll.
//
// Panics on out-of-range player.
func (rt *Runtime) ClearDice(playerIdx int) {
	checkPlayer("ClearDice", playerIdx)
	g := rt.Game
	for c := 0; c < engine.DiceColorCount; c++ {
		g.Counters[rt.diceSlot(playerIdx, c)].Value = 0
	}
}

// GetDiceCount returns the number of dice of the given color in the
// player's pool. Panics on out-of-range player or color.
func (rt *Runtime) GetDiceCount(playerIdx, color int) int {
	checkPlayer("GetDiceCount", playerIdx)
	checkColor("GetDiceCount", color)
	return rt.Game.Counters[rt.diceSlot(playerIdx, color)].Value
}

// DiceCounterID returns the raw counter ID for the given (player,
// color) slot. Always returns a valid (>= 0) counter ID — the dice
// index build panics when a counter is missing, so callers do not
// need to defend against -1.
//
// Panics on out-of-range player or color.
func (rt *Runtime) DiceCounterID(playerIdx, color int) int {
	checkPlayer("DiceCounterID", playerIdx)
	checkColor("DiceCounterID", color)
	return rt.diceSlot(playerIdx, color)
}

// SkillCost implements engine.DicePoolProvider. Returns the declared
// dice+energy cost of a skill by global skill ID, or (zero, false) if
// the skill isn't registered.
func (rt *Runtime) SkillCost(skillID int) (engine.Cost, bool) {
	ref, ok := rt.Skills.ByID[skillID]
	if !ok || ref == nil {
		return engine.Cost{}, false
	}
	return ref.Cost, true
}

// CardCost implements engine.DicePoolProvider. Returns the declared
// dice+energy cost of a card by ref, or (zero, false) if the card
// isn't registered.
func (rt *Runtime) CardCost(cardRef int) (engine.Cost, bool) {
	ref, ok := rt.Cards.ByRef[cardRef]
	if !ok || ref == nil {
		return engine.Cost{}, false
	}
	return ref.Cost, true
}

// DicePool returns the player's dice pool as an 8-slot snapshot for
// quick reads (used by cost affordability checks in Phase IV).
// Panics on out-of-range player.
func (rt *Runtime) DicePool(playerIdx int) [engine.DiceColorCount]int {
	checkPlayer("DicePool", playerIdx)
	var pool [engine.DiceColorCount]int
	for i := 0; i < engine.DiceColorCount; i++ {
		pool[i] = rt.Game.Counters[rt.diceSlot(playerIdx, i)].Value
	}
	return pool
}
