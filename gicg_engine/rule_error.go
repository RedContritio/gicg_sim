package engine

import "fmt"

// RuleError aborts execution of a broken DSL rule. A failed game cannot be
// continued or sampled; reset is required. FFI boundaries recover this type
// explicitly and expose the diagnostic to callers instead of fabricating data.
type RuleError struct {
	Cause                 error
	Round, Player, HookID int
	Source                string
}

func (e *RuleError) Error() string {
	return fmt.Sprintf("DSL rule failed (round=%d player=%d hook=%d source=%q): %v", e.Round, e.Player, e.HookID, e.Source, e.Cause)
}
func (e *RuleError) Unwrap() error { return e.Cause }

func (g *Game) FailRule(err error, hookID int) {
	if g.Failure == nil {
		source := ""
		if g.Hooks != nil && hookID >= 0 && hookID < len(g.Hooks.hooks) {
			source = g.Hooks.hooks[hookID].Source
		}
		g.Failure = &RuleError{Cause: err, Round: g.Round, Player: g.Turn, HookID: hookID, Source: source}
	}
	panic(g.Failure)
}

func (g *Game) RequireHealthy() {
	if g.Failure != nil {
		panic(g.Failure)
	}
}

func (g *Game) requireEffectDepth(operation string) {
	g.RequireHealthy()
	if g.depth > MaxDepth {
		g.FailRule(fmt.Errorf("%s exceeded effect depth limit %d (depth=%d)", operation, MaxDepth, g.depth), -1)
	}
}
