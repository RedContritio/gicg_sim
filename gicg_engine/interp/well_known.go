package interp

// Well-known counter names that form the stable API contract between DSL
// system files and the Go interpreter. DSL must declare counters with these
// exact internal names; Go code looks them up via
// rt.Counters.Entries[CounterXxx]. Renaming a constant here requires a
// matching rename in data/system/*.lua.
//
// Display names are separate (set via the declare_counter `display` option)
// and belong to the DSL alone — never hardcoded on the Go side.
const (
	// Player-scope
	CounterAliveCount = "alive_count"

	// Global
	CounterRoundNum    = "round_num"
	CounterFirstPlayer = "round1_first_player"

	// Self-scope (char counters — looked up via CharEntry, but the names
	// are stable here too for validation/lookup helpers)
	CounterHP     = "hp"
	CounterEnergy = "energy"
	CounterAlive  = "alive"
	CounterActive = "active"
)
