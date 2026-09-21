package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

const dataDir = "../../data"

// GameEnv bundles a Game + Runtime for testing.
//
// T is set by newGame so Step can auto-run post-step invariant checks
// against any test that drives the engine via this helper. Tests that
// want to exercise engine states the invariants would flag (e.g. the
// pre-fix D14 deadlock) can either clear T before the offending call
// or drive g.Step directly, bypassing the wrapper.
type GameEnv struct {
	G  *engine.Game
	RT *interp.Runtime
	T  *testing.T
}

// HP returns HP of player p, char c.
func (env *GameEnv) HP(p, c int) int {
	e := env.RT.Chars.BySlot[p][c]
	if e == nil {
		return -1
	}
	return env.G.Counters[e.HPCounterID].Value
}

// Energy returns energy of player p, char c.
func (env *GameEnv) Energy(p, c int) int {
	e := env.RT.Chars.BySlot[p][c]
	if e == nil {
		return -1
	}
	return env.G.Counters[e.EnergyCounterID].Value
}

// DiceTotal returns the total number of dice in player p's pool.
func (env *GameEnv) DiceTotal(p int) int {
	pool := env.RT.DicePool(p)
	total := 0
	for _, v := range pool {
		total += v
	}
	return total
}

// SetDice forcibly sets player p's dice pool to the given per-color
// counts, clearing other colors. Useful for tests that need a
// deterministic pool without waiting on rolls.
func (env *GameEnv) SetDice(p int, counts map[int]int) {
	env.RT.ClearDice(p)
	for color, n := range counts {
		cid := env.RT.DiceCounterID(p, color)
		if cid >= 0 {
			env.G.Counters[cid].Value = n
		}
	}
}

// Alive returns whether player p, char c is alive.
func (env *GameEnv) Alive(p, c int) bool {
	e := env.RT.Chars.BySlot[p][c]
	if e == nil {
		return false
	}
	return env.G.Players[p].Chars[c].Alive
}

// SkillID returns the skill ID for a char's named skill.
func (env *GameEnv) SkillID(charName, skillName string) int {
	e, ok := env.RT.Chars.ByName[charName]
	if !ok {
		return -1
	}
	id, ok := e.Skills[skillName]
	if !ok {
		return -1
	}
	return id
}

// FindAction finds a legal action by kind and skill/card name.
func (env *GameEnv) FindAction(kind engine.ActionKind, name string) int {
	if kind != engine.ActionReroll {
		if err := keepAllRerolls(env.G); err != nil {
			if env.T != nil {
				env.T.Helper()
				env.T.Fatal(err)
			}
			panic(err)
		}
	}
	actions := env.G.GetLegalActions()
	for i, a := range actions {
		if a.Kind != kind {
			continue
		}
		switch kind {
		case engine.ActionSkill:
			if n, ok := env.G.SkillNames[a.Index]; ok && n == name {
				return i
			}
		case engine.ActionCard:
			if a.Index < len(env.G.Players[a.PlayerIdx].Hand) {
				ref := env.G.Players[a.PlayerIdx].Hand[a.Index].Ref
				if n, ok := env.G.CardNames[ref]; ok && n == name {
					return i
				}
			}
		case engine.ActionEndTurn:
			return i
		}
	}
	return -1
}

func keepAllRerolls(g *engine.Game) error {
	for steps := 0; steps < 20; steps++ {
		actions := g.GetLegalActions()
		if len(actions) == 0 || actions[0].Kind != engine.ActionReroll {
			return nil
		}
		g.Step(0)
	}
	return fmt.Errorf("round-start reroll did not finish")
}

// Step executes action at index, handling targets. Runs the package
// post-step invariant check (see checkInvariants) so every test that
// drives the engine via this wrapper gets L1 deadlock protection for
// free. D14-class bugs (PhaseAction with zero legal actions, pending
// switch with no valid target, dead active char in a non-terminal
// phase) fail the enclosing test immediately.
func (env *GameEnv) Step(actionIdx int) engine.StepResult {
	env.RT.CurrentContextPlayer = env.G.Turn
	result := env.G.Step(actionIdx)
	if result == engine.StepNeedTarget {
		env.G.StepTarget(0)
	}
	env.checkInvariants(actionIdx)
	return result
}

// invariantErrors returns a list of invariant violations for the given
// game state. Pure function — no testing.T dependency — so it can be
// unit-tested against crafted states in TestInvariants_Synthetic.
//
// Invariants (skipped entirely when phase == GameOver):
//  1. PhaseAction / PhaseSelectActive → GetLegalActions() non-empty.
//     Captures D14: "engine entered a decision phase with no moves".
//  2. PendingAction{Switch} → target player has at least one alive
//     candidate (either a non-active char, or the current active is
//     itself dead and needs replacement).
//  3. Active char alive in PhaseAction, unless a forced switch is
//     already pending to replace them.
func invariantErrors(g *engine.Game, lastActionIdx int) []string {
	if g.Phase == engine.PhaseGameOver {
		return nil
	}
	var errs []string

	if g.Phase == engine.PhaseAction || g.Phase == engine.PhaseSelectActive {
		if len(g.GetLegalActions()) == 0 {
			errs = append(errs, fmt.Sprintf(
				"phase=%d has zero legal actions after Step(%d) "+
					"(turn=%d round=%d) — engine is deadlocked",
				g.Phase, lastActionIdx, g.Turn, g.Round))
		}
	}

	if g.PendingAction != nil && g.PendingAction.Kind == engine.ActionSwitch {
		pi := g.PendingAction.PlayerIdx
		if pi < 0 || pi >= len(g.Players) {
			errs = append(errs, fmt.Sprintf(
				"pending switch for invalid player %d", pi))
		} else {
			aliveOthers := 0
			for ci, c := range g.Players[pi].Chars {
				if c.Alive && ci != g.Players[pi].ActiveChar {
					aliveOthers++
				}
			}
			currentActiveAlive := false
			if ac := g.Players[pi].ActiveChar; ac >= 0 && ac < len(g.Players[pi].Chars) {
				currentActiveAlive = g.Players[pi].Chars[ac].Alive
			}
			if aliveOthers == 0 && !currentActiveAlive {
				errs = append(errs, fmt.Sprintf(
					"pending switch for P%d but no alive chars at all "+
						"(game should be over)", pi))
			}
		}
	}

	if g.Phase == engine.PhaseAction {
		for pi := 0; pi < len(g.Players); pi++ {
			ac := g.Players[pi].ActiveChar
			if ac < 0 || ac >= len(g.Players[pi].Chars) {
				continue
			}
			if !g.Players[pi].Chars[ac].Alive {
				if g.PendingAction != nil &&
					g.PendingAction.Kind == engine.ActionSwitch &&
					g.PendingAction.PlayerIdx == pi {
					continue
				}
				errs = append(errs, fmt.Sprintf(
					"P%d active=%d is dead in PhaseAction with no pending "+
						"switch (turn=%d round=%d)",
					pi, ac, g.Turn, g.Round))
			}
		}
	}
	return errs
}

// checkInvariants reports any invariant violations via env.T.Errorf.
// Runs automatically from Step when env.T is set (newGame path); tests
// constructing a GameEnv manually or exercising pathological states
// can leave T nil to suppress it.
func (env *GameEnv) checkInvariants(lastActionIdx int) {
	if env.T == nil {
		return
	}
	env.T.Helper()
	for _, msg := range invariantErrors(env.G, lastActionIdx) {
		env.T.Errorf("invariant: %s", msg)
	}
}

// StepSkill finds and executes a named skill. Returns false if not found.
func (env *GameEnv) StepSkill(skillName string) bool {
	idx := env.FindAction(engine.ActionSkill, skillName)
	if idx < 0 {
		return false
	}
	env.Step(idx)
	return true
}

// StepEndTurn executes EndTurn.
func (env *GameEnv) StepEndTurn() {
	idx := env.FindAction(engine.ActionEndTurn, "")
	if idx >= 0 {
		env.Step(idx)
	}
}

// PlayUntilTurn advances until it's the specified player's turn in PhaseAction.
func (env *GameEnv) PlayUntilTurn(player int, maxSteps int) bool {
	for i := 0; i < maxSteps; i++ {
		if env.G.Phase == engine.PhaseGameOver {
			return false
		}
		if env.G.Phase == engine.PhaseAction && env.G.Turn == player {
			return true
		}
		env.Step(0) // take first action
	}
	return false
}

// PlayN executes N steps with action 0.
func (env *GameEnv) PlayN(n int) {
	for i := 0; i < n; i++ {
		if env.G.Phase == engine.PhaseGameOver {
			return
		}
		actions := env.G.GetLegalActions()
		if len(actions) == 0 {
			return
		}
		env.Step(0)
	}
}

// PlayToEnd plays until game over or maxSteps. Always picks action 0.
func (env *GameEnv) PlayToEnd(maxSteps int) {
	for i := 0; i < maxSteps; i++ {
		if env.G.Phase == engine.PhaseGameOver {
			return
		}
		actions := env.G.GetLegalActions()
		if len(actions) == 0 {
			return
		}
		env.Step(0)
	}
}

// Setup helpers (NewGame / newGame / systemFiles / DSL path
// splitting) live in helpers_setup_test.go.
