package record

import (
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// StateView is the structured, JSON-serializable snapshot of the LIVE
// game state — everything a renderer (web UI, live replay player,
// Python test) needs to draw a board or assert invariants, as typed
// fields rather than the stringly-typed YAML that Export() emits.
//
// Unlike the writeState() text formatter which consumes an
// engine.StateSnapshot (a past-tense frozen state), ExportView reads
// directly from *interp.Runtime's Game, so it reflects whatever the
// game is doing right now. The two share the same roleMap + per-char
// counter walking logic.
type StateView struct {
	Phase       string        `json:"phase"` // "not_started" / "select_active" / "round_start" / "action" / "round_end" / "game_over"
	Round       int           `json:"round"`
	Turn        int           `json:"turn"`         // 0 or 1 — the acting player
	FirstPlayer int           `json:"first_player"` // who went first in round 1 (or -1 if not set yet)
	Winner      int           `json:"winner"`       // -1 until decided; 2 means draw
	Players     [2]PlayerView `json:"players"`
}

// PlayerView is everything a renderer needs for one side of the
// board: active char index, the full roster (HP/energy/status/…), the
// hand as human-readable card names, and deck/discard counts.
//
// Discard is emitted as a full ref+name list because IS-MCTS
// determinization uses it to subtract publicly-committed cards from
// the sampled hand/deck (docs/az/determinization.md). Zero-length =
// no cards discarded yet.
type PlayerView struct {
	ActiveChar int        `json:"active_char"` // index into Chars; -1 when not yet selected
	AliveCount int        `json:"alive_count"`
	Chars      []CharView `json:"chars"`
	Hand       []CardView `json:"hand"`
	DeckCount  int        `json:"deck_count"`
	Discard    []CardView `json:"discard"`
}

type CharView struct {
	Name      string       `json:"name"`
	Element   string       `json:"element"` // "none" / "fire" / "ice" / "water" / "electro" / "geo" / "anemo" / "dendro" / "physical"
	HP        int          `json:"hp"`
	HPMax     int          `json:"hp_max"`
	Energy    int          `json:"energy"`
	EnergyMax int          `json:"energy_max"`
	Alive     bool         `json:"alive"`
	Active    bool         `json:"active"`
	Statuses  []StatusView `json:"statuses"`
}

// StatusView is a non-role (buff / shield / element / summon / food / …)
// counter attached to a character. Only counters with value > 0 are
// included — zero-valued counters are noise.
type StatusView struct {
	Name  string `json:"name"`
	Value int    `json:"value"`
	Max   int    `json:"max"`
}

type CardView struct {
	Ref  int    `json:"ref"`
	Name string `json:"name"`
}

// ExportView builds a live StateView from the runtime's current Game.
// Safe to call at any phase — returns zero-valued fields where data
// isn't available yet (e.g. Phase=="not_started" early in setup).
func ExportView(rt *interp.Runtime) *StateView {
	g := rt.Game
	roleMap := buildRoleMap(rt)

	view := &StateView{
		Phase:       phaseName(g.Phase),
		Round:       readGlobalCounter(g, roleMap, RoleRoundNum),
		Turn:        g.Turn,
		FirstPlayer: readGlobalCounter(g, roleMap, RoleFirstPlayer),
		Winner:      g.Winner,
	}

	for pi := 0; pi < 2; pi++ {
		view.Players[pi] = buildPlayerView(g, rt, roleMap, pi)
	}
	return view
}

// buildPlayerView walks the live state of one player: active char,
// per-char status, hand, deck count.
func buildPlayerView(g *engine.Game, rt *interp.Runtime, roleMap RoleMap,
	pi int) PlayerView {
	pv := PlayerView{
		ActiveChar: g.Players[pi].ActiveChar,
		AliveCount: readPlayerCounter(g, roleMap, RoleAliveCount, pi),
		DeckCount:  len(g.Players[pi].Deck),
	}

	for ci := range g.Players[pi].Chars {
		pv.Chars = append(pv.Chars, buildCharView(g, rt, roleMap, pi, ci))
	}

	for _, h := range g.Players[pi].Hand {
		pv.Hand = append(pv.Hand, CardView{
			Ref:  h.Ref,
			Name: g.CardNames[h.Ref],
		})
	}
	for _, d := range g.Players[pi].Discard {
		pv.Discard = append(pv.Discard, CardView{
			Ref:  d.Ref,
			Name: g.CardNames[d.Ref],
		})
	}
	return pv
}

// buildCharView collects all counters owned by (pi, ci), splits them
// into roled fields (hp/energy/alive/active) vs. free-form statuses,
// and packs the result as a CharView.
func buildCharView(g *engine.Game, rt *interp.Runtime, roleMap RoleMap,
	pi, ci int) CharView {
	cv := CharView{
		Name:    charName(g, pi, ci),
		Element: elementName(g.Players[pi].Chars[ci].Element),
	}

	for id, role := range roleMap {
		if !isCharCounter(g, id, pi, ci) {
			continue
		}
		c := g.Counters[id]
		switch role {
		case RoleHP:
			cv.HP = c.Value
			cv.HPMax = c.Max
		case RoleEnergy:
			cv.Energy = c.Value
			cv.EnergyMax = c.Max
		case RoleAlive:
			cv.Alive = c.Value > 0
		case RoleActive:
			// Active counter doesn't track current state — derive from
			// Players[pi].ActiveChar, same logic as writeCharState().
			cv.Active = g.Players[pi].ActiveChar == ci
		}
	}

	// Free-form status counters (no role, value > 0)
	for id, displayName := range g.CounterNames {
		if !isCharCounter(g, id, pi, ci) {
			continue
		}
		if roleMap[id] != RoleNone {
			continue
		}
		c := g.Counters[id]
		if c.Value <= 0 {
			continue
		}
		cv.Statuses = append(cv.Statuses, StatusView{
			Name:  displayName,
			Value: c.Value,
			Max:   c.Max,
		})
	}
	return cv
}

// readPlayerCounter returns the value of the first player-scope
// counter of the given role for player pi, or 0 if missing.
func readPlayerCounter(g *engine.Game, roleMap RoleMap, role Role, pi int) int {
	for id, r := range roleMap {
		if r != role {
			continue
		}
		if !isPlayerCounter(g, id, pi) {
			continue
		}
		return g.Counters[id].Value
	}
	return 0
}

// readGlobalCounter returns the value of the first counter with the
// given role (typically round_num / first_player), or -1 if missing.
func readGlobalCounter(g *engine.Game, roleMap RoleMap, role Role) int {
	for id, r := range roleMap {
		if r == role {
			return g.Counters[id].Value
		}
	}
	return -1
}

// elementName maps an engine.Element enum to a short JSON string.
// Kept parallel to DiceColor's 7-element palette; ElemNone + ElemPhysical
// are distinct sentinels (Physical damage != no element).
func elementName(e engine.Element) string {
	switch e {
	case engine.ElemFire:
		return "fire"
	case engine.ElemIce:
		return "ice"
	case engine.ElemWater:
		return "water"
	case engine.ElemElectro:
		return "electro"
	case engine.ElemGeo:
		return "geo"
	case engine.ElemAnemo:
		return "anemo"
	case engine.ElemDendro:
		return "dendro"
	case engine.ElemPhysical:
		return "physical"
	}
	return "none"
}

func phaseName(p engine.Phase) string {
	switch p {
	case engine.PhaseNotStarted:
		return "not_started"
	case engine.PhaseSelectActive:
		return "select_active"
	case engine.PhaseRoundStart:
		return "round_start"
	case engine.PhaseAction:
		return "action"
	case engine.PhaseRoundEnd:
		return "round_end"
	case engine.PhaseGameOver:
		return "game_over"
	}
	return "unknown"
}
