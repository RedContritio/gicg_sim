package engine

const ObsBuffRows = 1024
const ObsBuffFields = 16
const ObsBuffSlots = ObsBuffRows * ObsBuffFields

// One row per (live instance, rule hook), retaining instance order. Hook slots
// reference the SAME encoded rule definitions used by actions, not card IDs.
// Fields: valid, relative owner, char (-1 team), value, duration (-1 permanent),
// progress, instance position, active hook slot, trigger kind, category, death-bound,
// round-order group (0 ordinary, 1 summon undecided, 2 first, 3 second),
// entity kind, source counter SID, target player, target character.
func (g *Game) writeBuffObs(out []int32, perspective int) int {
	hooks := g.BuildRawToActiveHookIdx()
	row := 0
	kinds := g.observationReferenceKinds()
	for position, instance := range g.Buffs {
		def := g.BuffDefinitions[instance.Definition]
		p, c := g.GetCounterChar(def.CounterID)[0], g.GetCounterChar(def.CounterID)[1]
		relative := p
		if p >= 0 {
			relative = 0
			if p != perspective {
				relative = 1
			}
		}
		value, duration, progress := g.BuffValues(instance)
		if kinds[def.CounterID] != 0 {
			value = int(referencePresence(value))
		}
		if kinds[def.DurationID] != 0 {
			duration = int(referencePresence(duration))
		}
		if kinds[def.ProgressID] != 0 {
			progress = int(referencePresence(progress))
		}
		for _, h := range g.Hooks.AllHooks() {
			slot, ok := hooks[h.ID]
			matches := false
			for _, id := range def.HookIDs {
				if h.ID == id {
					matches = true
					break
				}
			}
			if !ok || !matches {
				continue
			}
			if row >= ObsBuffRows {
				panic("buff observation capacity exceeded")
			}
			death := 0
			if def.RemoveOnDeath {
				death = 1
			}
			zone := 0
			if def.Summon {
				zone = 1
				if g.FirstEnd >= 0 {
					zone = 3
					if p == g.FirstEnd {
						zone = 2
					}
				}
			}
			values := []int{1, relative, c, value, duration, progress, position, slot, int(h.Type), h.Priority, death, zone, EntityBuff, -1, -1, -1}
			for i, v := range values {
				out[row*ObsBuffFields+i] = int32(v)
			}
			row++
		}
	}
	return row
}
