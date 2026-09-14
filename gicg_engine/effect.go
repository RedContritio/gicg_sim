package engine

import "fmt"

// ExecuteEffect is the native scripting/test entry point for a compound effect.
// It supplies actor context and preserves the entire remaining effect if input
// is required. Call Step/StepTarget to answer that input, just as for an action.
//
// fn must keep gameplay state in the supplied Game, not in captured mutable
// variables or external I/O. The body may be rerun to reconstruct a suspended
// stack. Capture immutable IDs/parameters; resolve a runtime through game.Extra.
// Manually pushing a frame does not provide a resumable operation boundary.
func (g *Game) ExecuteEffect(frame EventFrame, fn func(*Game)) StepResult {
	if fn == nil {
		g.FailRule(fmt.Errorf("ExecuteEffect requires an effect body"), -1)
	}
	return g.runBoundary(boundaryOperation{kind: boundaryEffect, frame: frame, fn: fn})
}
