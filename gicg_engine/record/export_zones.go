package record

import engine "gicg_mono/gicg_engine"

// Project actual support slots and ordered buff instances, never guessed names.
// This read-only view does not alter resolution order or the NN observation.
func buildPlayerZones(g *engine.Game, player int) (supports, summons, statuses []StatusView) {
	supports = make([]StatusView, 0)
	summons = make([]StatusView, 0)
	statuses = make([]StatusView, 0)
	supportBuffs := make(map[uint64]bool)
	for _, support := range g.Players[player].Supports {
		item := StatusView{Name: g.CardNames[support.Ref], Value: 1}
		if support.BuffID != 0 {
			supportBuffs[support.BuffID] = true
			for _, buff := range g.Buffs {
				if buff.ID == support.BuffID {
					item.Value, _, _ = g.BuffValues(buff)
					item.Max = g.Counters[g.BuffDefinitions[buff.Definition].CounterID].Max
					break
				}
			}
		}
		supports = append(supports, item)
	}
	for _, buff := range g.Buffs {
		def := g.BuffDefinitions[buff.Definition]
		owner := g.GetCounterChar(def.CounterID)
		if owner[0] != player || supportBuffs[buff.ID] {
			continue
		}
		value, _, _ := g.BuffValues(buff)
		item := StatusView{Name: g.CounterNames[def.CounterID], Value: value, Max: g.Counters[def.CounterID].Max}
		if def.Summon {
			summons = append(summons, item)
		} else if owner[1] < 0 {
			statuses = append(statuses, item)
		}
	}
	return
}
