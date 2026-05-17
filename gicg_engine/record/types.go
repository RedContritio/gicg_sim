package record

// Record is a parsed game record.
type Record struct {
	Rounds []Round
	Winner int // -1 if not set
}

type Round struct {
	Number  int
	Start   *State // state at the beginning of this round (= end of previous round)
	Actions []Action
}

// State is a full game state snapshot at a point in time.
type State struct {
	FirstPlayer int // 0 or 1: who goes first in this round
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
)

type Action struct {
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
