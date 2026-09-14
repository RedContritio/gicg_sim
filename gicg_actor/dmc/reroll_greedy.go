package dmc

import engine "gicg_mono/gicg_engine"

// Fixed dice-value baseline: reroll a color iff a uniformly rolled die has
// greater expected value under the existing payment heuristic. No RNG peeking.
func greedyRerollChoice(g *engine.Game) int {
	f := g.PendingDice
	if f.Color == engine.DiceColorCount {
		return 0
	}
	values := buildColorValues(g, f.Player, f.Pool)
	sum := 0
	for _, value := range values {
		sum += value
	}
	if sum > engine.DiceColorCount*values[f.Color] {
		return f.Pool[f.Color]
	}
	return 0
}
