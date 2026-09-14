package engine

import "sort"

// Execution rows use the existing typed entity transport. Value = completeness,
// duration = target mode, progress = PC, trigger = program kind, category =
// battle action, death-bound = forced. Binding rows are an unordered set of
// already-applied rule hooks (not raw IDs). Row position 0 binds to the frame.
func (g *Game) writeSuspensionObs(out []int32, perspective, row int) int {
	if g.PendingDice != nil {
		return g.writeDiceSelectionObs(out, perspective, row)
	}
	kind, waiting := g.SuspensionKind()
	if !waiting {
		return row
	}
	hooks := g.BuildRawToActiveHookIdx()
	owner, char, hook, complete, mode, pc, battle, forced := -1, -1, -1, 0, 0, 0, 0, 0
	var bindings []int
	if kind == ProgramCardTarget {
		f := g.PendingCardTarget
		f.validate(g)
		owner, char = f.PlayerIdx, g.Players[f.PlayerIdx].ActiveChar
		mode, pc = f.TargetMode, int(f.PC)
		battle = int(boolToInt32(f.BattleAction))
		if raw, ok := g.CanonicalCardHooks[f.CardRef]; ok {
			if active, ok := hooks[raw]; ok {
				hook = active
				if perspective == owner {
					complete = 1
				}
			}
		}
		// Applied conditions can depend on private state. Only the card's
		// owner receives these locals; alternate observers get no flags/count.
		if perspective == owner {
			for raw, applied := range f.AppliedMods {
				if !applied {
					continue
				}
				if active, ok := hooks[raw]; ok {
					bindings = append(bindings, active)
				} else {
					complete = 0 // opaque native rule, never emit its raw ID
				}
			}
		}
	} else if g.PendingAction != nil {
		owner = g.PendingAction.PlayerIdx
		forced = int(boolToInt32(g.PendingAction.Forced))
		if kind == ProgramSwitchTarget {
			complete = 1
		}
	}
	write := func(entityKind, rule int) {
		if row >= ObsBuffRows {
			panic("suspension observation capacity exceeded")
		}
		values := []int32{1, relativePlayer(owner, perspective), int32(char), int32(complete), int32(mode),
			int32(pc), 0, int32(rule), int32(kind), int32(battle), int32(forced), 0,
			int32(entityKind), -1, -1, -1}
		copy(out[row*ObsBuffFields:], values)
		row++
	}
	write(EntityExecutionFrame, hook)
	sort.Ints(bindings) // deterministic transport; no semantic order embedding
	for _, binding := range bindings {
		write(EntityExecutionBinding, binding)
	}
	return g.writePublicCauseObs(out, perspective, row, hooks)
}
