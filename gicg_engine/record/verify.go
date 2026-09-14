package record

import (
	"fmt"
	"sort"
	"strings"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// Diff represents a single mismatch.
type Diff struct {
	Path     string      // e.g. "P0.赤蝶.生命"
	Expected interface{} // from record
	Actual   interface{} // from game
}

func (d Diff) String() string {
	return fmt.Sprintf("  %s: expected=%v actual=%v", d.Path, d.Expected, d.Actual)
}

// VerifyState compares a runtime's current state with a recorded state.
// Returns a list of diffs (empty = match).
func VerifyState(rt *interp.Runtime, state *State) []Diff {
	var diffs []Diff
	g := rt.Game
	first := g.Turn
	if g.Phase == engine.PhaseRoundStart && g.FirstEnd >= 0 {
		first = g.FirstEnd
	}
	if first != state.FirstPlayer {
		diffs = append(diffs, Diff{Path: "先手", Expected: state.FirstPlayer, Actual: first})
	}
	roleMap := buildRoleMap(rt)
	for pi, pe := range [2]PlayerState{state.P0, state.P1} {
		if state.ActiveChars != nil && g.Players[pi].ActiveChar != state.ActiveChars[pi] {
			diffs = append(diffs, Diff{Path: fmt.Sprintf("P%d.active_char", pi), Expected: state.ActiveChars[pi], Actual: g.Players[pi].ActiveChar})
		}
		diffs = append(diffs, verifyPlayer(rt, roleMap, pi, pe, nil, state.ActiveChars == nil)...)
	}
	return diffs
}

// VerifyAgainstSnap compares a snapshot against a recorded state.
func VerifyAgainstSnap(rt *interp.Runtime, snap *engine.StateSnapshot, state *State) []Diff {
	var diffs []Diff
	if snap.FirstPlayer != state.FirstPlayer {
		diffs = append(diffs, Diff{Path: "先手", Expected: state.FirstPlayer, Actual: snap.FirstPlayer})
	}
	roleMap := buildRoleMap(rt)
	for pi, pe := range [2]PlayerState{state.P0, state.P1} {
		if state.ActiveChars != nil && snap.ActiveChars[pi] != state.ActiveChars[pi] {
			diffs = append(diffs, Diff{Path: fmt.Sprintf("P%d.active_char", pi), Expected: state.ActiveChars[pi], Actual: snap.ActiveChars[pi]})
		}
		diffs = append(diffs, verifyPlayer(rt, roleMap, pi, pe, snap, state.ActiveChars == nil)...)
	}
	return diffs
}

// counterVal returns a counter's value from snap if provided, else from live state.
func counterVal(g *engine.Game, snap *engine.StateSnapshot, id int) int {
	if snap != nil && id < len(snap.Counters) {
		return snap.Counters[id]
	}
	return g.Counters[id].Value
}

func verifyPlayer(rt *interp.Runtime, roleMap RoleMap, pi int, pe PlayerState, snap *engine.StateSnapshot, legacyActive bool) []Diff {
	var diffs []Diff
	g := rt.Game

	// Player-scope counters (keyed in expected.Counters by display name)
	for expName, expVal := range pe.Counters {
		id := findPlayerCounterByDisplay(g, pi, expName)
		if id < 0 {
			diffs = append(diffs, Diff{
				Path: fmt.Sprintf("P%d.%s", pi, expName), Expected: expVal, Actual: "missing",
			})
			continue
		}
		actual := counterVal(g, snap, id)
		if actual != expVal {
			diffs = append(diffs, Diff{
				Path: fmt.Sprintf("P%d.%s", pi, expName), Expected: expVal, Actual: actual,
			})
		}
	}

	// Hand (by card names, order-insensitive)
	var actualHand []string
	var handRefs []int
	if snap != nil {
		handRefs = snap.Hands[pi]
	} else {
		for _, card := range g.Players[pi].Hand {
			handRefs = append(handRefs, card.Ref)
		}
	}
	for _, ref := range handRefs {
		if n, ok := g.CardNames[ref]; ok {
			actualHand = append(actualHand, n)
		}
	}
	sort.Strings(actualHand)
	expectedHand := append([]string(nil), pe.Hand...)
	sort.Strings(expectedHand)
	if !stringsEqual(actualHand, expectedHand) {
		diffs = append(diffs, Diff{
			Path:     fmt.Sprintf("P%d.手牌", pi),
			Expected: strings.Join(expectedHand, ","),
			Actual:   strings.Join(actualHand, ","),
		})
	}

	// Chars
	for _, expected := range pe.Chars {
		ci := -1
		for c := range g.Players[pi].Chars {
			if name, ok := g.CharNames[[2]int{pi, c}]; ok && name == expected.Name {
				ci = c
				break
			}
		}
		if ci < 0 {
			diffs = append(diffs, Diff{
				Path:     fmt.Sprintf("P%d.%s", pi, expected.Name),
				Expected: "present", Actual: "missing",
			})
			continue
		}
		diffs = append(diffs, verifyChar(rt, roleMap, pi, ci, expected, snap, legacyActive)...)
	}
	return diffs
}

func verifyChar(rt *interp.Runtime, roleMap RoleMap, pi, ci int, expected CharFullState, snap *engine.StateSnapshot, legacyActive bool) []Diff {
	var diffs []Diff
	g := rt.Game
	path := fmt.Sprintf("P%d.%s", pi, expected.Name)

	// Build a map of (display_name → counter_id) for this char's counters.
	charCounters := make(map[string]int)
	for id, name := range g.CounterNames {
		if isCharCounter(g, id, pi, ci) {
			charCounters[name] = id
		}
	}

	// Compare each expected counter value against the live/snap state.
	for expName, expVal := range expected.Counters {
		id, ok := charCounters[expName]
		if !ok {
			diffs = append(diffs, Diff{
				Path: path + "." + expName, Expected: expVal, Actual: "missing",
			})
			continue
		}
		var actual int
		if legacyActive && roleMap[id] == RoleActive {
			// Active state comes from engine ActiveChars, not the counter.
			activeCi := -1
			if snap != nil {
				activeCi = snap.ActiveChars[pi]
			} else {
				activeCi = g.Players[pi].ActiveChar
			}
			if activeCi == ci {
				actual = 1
			} else {
				actual = 0
			}
		} else {
			actual = counterVal(g, snap, id)
		}
		if actual != expVal {
			diffs = append(diffs, Diff{
				Path: path + "." + expName, Expected: expVal, Actual: actual,
			})
		}
	}

	// Also flag any non-zero char counters that WEREN'T in the expected record.
	// We only flag counters without a role (status counters); role counters
	// are handled via explicit Counters keys above.
	for id, name := range g.CounterNames {
		if !isCharCounter(g, id, pi, ci) {
			continue
		}
		if roleMap[id] != RoleNone {
			continue
		}
		if _, ok := expected.Counters[name]; ok {
			continue
		}
		actual := counterVal(g, snap, id)
		if actual > 0 {
			diffs = append(diffs, Diff{
				Path: path + "." + name, Expected: 0, Actual: actual,
			})
		}
	}
	return diffs
}

// findPlayerCounterByDisplay looks up a player-scope counter whose display
// name matches the given string.
func findPlayerCounterByDisplay(g *engine.Game, pi int, displayName string) int {
	for id, name := range g.CounterNames {
		if name != displayName {
			continue
		}
		if isPlayerCounter(g, id, pi) {
			return id
		}
	}
	return -1
}

func stringsEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
