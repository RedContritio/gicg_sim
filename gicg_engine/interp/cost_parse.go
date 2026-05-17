package interp

import (
	engine "gicg_mono/gicg_engine"
)

// diceColorKeys maps DSL dice-color keys to DiceColor indices.
// Only the 7 elemental colors are valid specific-cost keys; omni is
// a payment-time substitute, not a declaration-time cost.
var diceColorKeys = map[string]int{
	"fire":    engine.DiceColorFire,
	"ice":     engine.DiceColorIce,
	"water":   engine.DiceColorWater,
	"electro": engine.DiceColorElectro,
	"geo":     engine.DiceColorGeo,
	"anemo":   engine.DiceColorAnemo,
	"dendro":  engine.DiceColorDendro,
}

// parseDices parses a `{ fire = 1, match = 2, any = 3, ... }` table
// into a DiceCost. Keys:
//   - fire/ice/water/electro/geo/anemo/dendro: specific element slots
//   - match: N dice of the same (any) color (unimplemented, panics at
//     enumeration time if used)
//   - any: N dice of any color
//
// Unknown keys are ignored.
func parseDices(t *Table) engine.DiceCost {
	cost := engine.DiceCost{}
	if t == nil {
		return cost
	}
	for k, v := range t.Fields {
		n, _ := ToInt(v)
		if n <= 0 {
			continue
		}
		if idx, ok := diceColorKeys[k]; ok {
			cost.Specific[idx] = n
			continue
		}
		switch k {
		case "match":
			cost.Match = n
		case "any":
			cost.Any = n
		}
	}
	return cost
}

// parseCost parses a `{ dices = {...}, energy = N }` table into a
// full Cost struct. Missing `dices` → zero DiceCost. Missing
// `energy` → 0. Unknown top-level keys are ignored for forward
// compatibility (e.g. future "shield" or "card" cost components).
func parseCost(t *Table) engine.Cost {
	cost := engine.Cost{}
	if t == nil {
		return cost
	}
	if dt, ok := t.Fields["dices"].(*Table); ok {
		cost.Dices = parseDices(dt)
	}
	if ev, ok := t.Fields["energy"]; ok {
		cost.Energy, _ = ToInt(ev)
	}
	return cost
}
