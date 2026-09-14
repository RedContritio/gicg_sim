package record

import (
	"encoding/json"
	engine "gicg_mono/gicg_engine"
)

// Record is a parsed game record.
type Record struct {
	Config *ReplayConfig
	Rounds []Round
	Winner int // -1 if not set
}

type Round struct {
	Number  int
	Start   *State // state at the beginning of this round (= end of previous round)
	Actions []Action
}

// State combines the legacy human-readable projection with an optional exact
// checkpoint. Legacy fields alone do not represent every gameplay field.
type State struct {
	Checkpoint  json.RawMessage
	ActiveChars *[2]int // engine slots, independent of DSL active counters
	FirstPlayer int     // 0 or 1: who goes first in this round
	P0          PlayerState
	P1          PlayerState
}

type PlayerState struct {
	Hand  []string
	Deck  []string
	Chars []CharFullState
	// Player-scope counter values keyed by display name (e.g. "行动点" → 5,
	// "存活数" → 3). Populated by Export from g.CounterNames; interpreted by
	// Verify/Load using engine.Game + interp.Runtime context.
	Counters map[string]int
}

// ActionKind for Action.Kind
const (
	ActSkill   = "skill"
	ActCard    = "card"
	ActSwitch  = "switch"
	ActEndTurn = "end_turn"
	ActTune    = "tune"
	ActReroll  = "reroll"
)

type Action struct {
	Input  *engine.ActionInput
	Player int    // 0 or 1
	Kind   string // ActSkill, ActCard, ActSwitch, ActEndTurn
	Name   string // skill/card/target-char name
	// Optional target for cards that need one. TargetPlayer is -1 if absent.
	TargetPlayer int
	TargetChar   string
	// Free-form effect lines for debugging/display (not used during replay)
	Effects []string
}

type CharFullState struct {
	Name string
	// Char-scope counter values keyed by display name. Includes hp/energy/
	// alive/active as well as any status counters (蝶火_active, 雷元素附着…).
	// alive/active counters are bool-valued in YAML (true/false) but stored
	// as int (1/0) here for uniform handling.
	Counters map[string]int
}
