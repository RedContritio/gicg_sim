package record

import (
	"fmt"
	"sort"
	"strings"

	engine "gicg_mono/gicg_engine"
)

// writeState writes the state snapshot as a `state:` block.
func writeState(b *strings.Builder, g *engine.Game, roleMap RoleMap, snap *engine.StateSnapshot) {
	b.WriteString("  state:\n")
	fmt.Fprintf(b, "    先手: P%d\n", snap.FirstPlayer)
	for pi := 0; pi < 2; pi++ {
		fmt.Fprintf(b, "    P%d:\n", pi)
		fmt.Fprintf(b, "      手牌: %s\n", cardListStr(g, snap.Hands[pi]))
		fmt.Fprintf(b, "      牌组: %s\n", cardListStr(g, snap.Decks[pi]))
		b.WriteString("      角色:\n")
		for ci := range g.Players[pi].Chars {
			writeCharState(b, g, roleMap, snap, pi, ci)
		}
	}
}

// writeCharState emits one char's inline state block.
func writeCharState(b *strings.Builder, g *engine.Game, roleMap RoleMap, snap *engine.StateSnapshot, pi, ci int) {
	name := charName(g, pi, ci)

	// Collect all counters owned by (pi, ci), split by role category
	type kv struct {
		name  string
		value int
		role  Role
	}
	var ordered []kv
	var status []kv
	for id, role := range roleMap {
		if !isCharCounter(g, id, pi, ci) {
			continue
		}
		value := snap.Counters[id]
		// Active counter doesn't track engine state directly; derive from
		// the snapshot's ActiveChars so the YAML reflects reality.
		if role == RoleActive {
			if snap.ActiveChars[pi] == ci {
				value = 1
			} else {
				value = 0
			}
		}
		ordered = append(ordered, kv{g.CounterNames[id], value, role})
	}
	// Sort ordered by role priority (hp, energy, alive, active)
	sort.Slice(ordered, func(i, j int) bool {
		return rolePriority(ordered[i].role) < rolePriority(ordered[j].role)
	})

	// Collect status counters (no role) owned by this char
	for id, displayName := range g.CounterNames {
		if !isCharCounter(g, id, pi, ci) {
			continue
		}
		if roleMap[id] != RoleNone {
			continue
		}
		v := snap.Counters[id]
		if v <= 0 {
			continue
		}
		status = append(status, kv{displayName, v, RoleNone})
	}
	sort.Slice(status, func(i, j int) bool { return status[i].name < status[j].name })

	// Format ordered fields (hp/energy/alive/active)
	var parts []string
	for _, e := range ordered {
		parts = append(parts, formatFieldValue(e.name, e.value, e.role))
	}
	statusStr := ""
	if len(status) > 0 {
		var sp []string
		for _, s := range status {
			sp = append(sp, fmt.Sprintf("%s: %d", s.name, s.value))
		}
		statusStr = ", 状态: { " + strings.Join(sp, ", ") + " }"
	}
	fmt.Fprintf(b, "        %s: { %s%s }\n", name, strings.Join(parts, ", "), statusStr)
}

func formatFieldValue(name string, value int, role Role) string {
	// alive/active rendered as true/false for readability
	if role == RoleAlive || role == RoleActive {
		return fmt.Sprintf("%s: %v", name, value > 0)
	}
	return fmt.Sprintf("%s: %d", name, value)
}

func rolePriority(r Role) int {
	switch r {
	case RoleHP:
		return 0
	case RoleEnergy:
		return 1
	case RoleAlive:
		return 2
	case RoleActive:
		return 3
	default:
		return 100
	}
}

func charName(g *engine.Game, p, c int) string {
	if n, ok := g.CharNames[[2]int{p, c}]; ok {
		return n
	}
	return fmt.Sprintf("P%dC%d", p, c)
}

func cardListStr(g *engine.Game, refs []int) string {
	if len(refs) == 0 {
		return "[]"
	}
	names := make([]string, len(refs))
	for i, r := range refs {
		if n, ok := g.CardNames[r]; ok {
			names[i] = n
		} else {
			names[i] = fmt.Sprintf("?%d", r)
		}
	}
	return "[" + strings.Join(names, ", ") + "]"
}
