package engine

import "fmt"

// Validate registry-bound locals before publishing/restoring a target frame.
// This is state validation, not proof that an arbitrary external checkpoint
// was reached by legal play. It never executes hooks or mutates the receiver.
func (g *Game) validateTargetCheckpoint(f *TargetFrame, phase Phase) error {
	if f == nil {
		return nil
	}
	if err := f.validationError(); err != nil {
		return err
	}
	if phase != PhaseAction {
		return fmt.Errorf("target frame requires action phase")
	}
	if _, ok := g.CardNames[f.CardRef]; !ok {
		return fmt.Errorf("target frame refers to unknown card")
	}
	known := map[int]bool{}
	for _, hook := range g.Hooks.AllHooks() {
		known[hook.ID] = true
	}
	for id := range f.AppliedMods {
		if !known[id] {
			return fmt.Errorf("target frame refers to unknown modifier hook")
		}
	}
	return nil
}
