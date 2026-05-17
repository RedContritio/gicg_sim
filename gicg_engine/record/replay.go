package record

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// Replayer drives a Game through a Record's action sequence.
type Replayer struct {
	Runtime *interp.Runtime
	Rec     *Record
}

// findActionIdx locates a legal action matching the given descriptor.
func findActionIdx(g *engine.Game, desc Action) int {
	actions := g.GetLegalActions()
	for i, a := range actions {
		if a.PlayerIdx != desc.Player {
			continue
		}
		switch desc.Kind {
		case ActSkill:
			if a.Kind != engine.ActionSkill {
				continue
			}
			if n, ok := g.SkillNames[a.Index]; ok && n == desc.Name {
				return i
			}
		case ActCard:
			if a.Kind != engine.ActionCard {
				continue
			}
			if a.Index < len(g.Players[a.PlayerIdx].Hand) {
				ref := g.Players[a.PlayerIdx].Hand[a.Index].Ref
				if n, ok := g.CardNames[ref]; ok && n == desc.Name {
					return i
				}
			}
		case ActSwitch:
			if a.Kind != engine.ActionSwitch {
				continue
			}
			if n, ok := g.CharNames[[2]int{a.PlayerIdx, a.Index}]; ok && n == desc.Name {
				return i
			}
		case ActEndTurn:
			if a.Kind == engine.ActionEndTurn {
				return i
			}
		}
	}
	return -1
}

// Step executes one action from the record at the given round and action index.
func (r *Replayer) Step(round int, actIdx int) error {
	g := r.Runtime.Game
	if round < 1 || round > len(r.Rec.Rounds) {
		return fmt.Errorf("round %d out of range", round)
	}
	rd := r.Rec.Rounds[round-1]
	if actIdx >= len(rd.Actions) {
		return fmt.Errorf("action %d out of range for round %d", actIdx, round)
	}
	desc := rd.Actions[actIdx]
	idx := findActionIdx(g, desc)
	if idx < 0 {
		return fmt.Errorf("round %d action %d: no legal match for P%d %s %q (turn=%d, phase=%d)",
			round, actIdx, desc.Player, desc.Kind, desc.Name, g.Turn, g.Phase)
	}
	r.Runtime.CurrentContextPlayer = g.Turn
	result := g.Step(idx)
	if result == engine.StepNeedTarget {
		tIdx := 0
		if desc.TargetPlayer >= 0 && desc.TargetChar != "" {
			tIdx = findTargetIdx(g, desc.TargetPlayer, desc.TargetChar)
			if tIdx < 0 {
				return fmt.Errorf("round %d action %d: target P%d %s not found among legal targets",
					round, actIdx, desc.TargetPlayer, desc.TargetChar)
			}
		}
		g.StepTarget(tIdx)
	}
	return nil
}

// findTargetIdx returns the index of (player, charName) in the current legal-target list.
func findTargetIdx(g *engine.Game, player int, charName string) int {
	targets := g.GetLegalActions()
	for i, a := range targets {
		if a.PlayerIdx != player {
			continue
		}
		if n, ok := g.CharNames[[2]int{a.PlayerIdx, a.Index}]; ok && n == charName {
			return i
		}
	}
	return -1
}

// PlayRound executes all actions of a single round.
func (r *Replayer) PlayRound(round int) error {
	g := r.Runtime.Game
	rd := r.Rec.Rounds[round-1]
	for i := range rd.Actions {
		if g.Phase == engine.PhaseGameOver {
			return nil
		}
		if err := r.Step(round, i); err != nil {
			return err
		}
	}
	return nil
}

// PlayAll plays all rounds to completion.
func (r *Replayer) PlayAll() error {
	g := r.Runtime.Game
	for i := range r.Rec.Rounds {
		if g.Phase == engine.PhaseGameOver {
			return nil
		}
		if err := r.PlayRound(i + 1); err != nil {
			return err
		}
	}
	return nil
}

// TotalSteps returns the total number of actions across all rounds in rec.
// Used by web UI replay scrubbers to bound the step slider.
func TotalSteps(rec *Record) int {
	n := 0
	for _, r := range rec.Rounds {
		n += len(r.Actions)
	}
	return n
}

// ExtractTeams pulls char rosters out of the record's first round start
// state. Useful for reconstructing a compatible Game from a bare YAML
// file when the caller doesn't already know which chars were played.
func ExtractTeams(rec *Record) ([2][]string, error) {
	var teams [2][]string
	if len(rec.Rounds) == 0 || rec.Rounds[0].Start == nil {
		return teams, fmt.Errorf("record has no round-start state")
	}
	start := rec.Rounds[0].Start
	for _, cs := range start.P0.Chars {
		teams[0] = append(teams[0], cs.Name)
	}
	for _, cs := range start.P1.Chars {
		teams[1] = append(teams[1], cs.Name)
	}
	return teams, nil
}

// ReplayTo advances rt's game state to the point immediately after the
// first `step` actions of rec have been executed. `step` is a global
// index counted across all rounds; step=0 returns the initial state of
// round 1, step=TotalSteps(rec) returns the terminal state.
//
// The runtime must already be initialized with matching teams and card
// declarations. Implementation: jump to the target round via record.Load
// (fast, cached snapshot) then Step forward any remaining in-round
// actions. This avoids re-running every preceding round at the cost of
// trusting each round's cached Start snapshot.
func ReplayTo(rt *interp.Runtime, rec *Record, step int) error {
	if step < 0 {
		return fmt.Errorf("step %d must be non-negative", step)
	}
	total := TotalSteps(rec)
	if step > total {
		return fmt.Errorf("step %d exceeds total %d", step, total)
	}
	// Map global step → (round, local action index within that round).
	targetRound := 1
	localIdx := 0
	remaining := step
	for ri, r := range rec.Rounds {
		if remaining < len(r.Actions) {
			targetRound = ri + 1
			localIdx = remaining
			break
		}
		remaining -= len(r.Actions)
		targetRound = ri + 1
		localIdx = len(r.Actions)
	}
	if err := Load(rt, rec, targetRound); err != nil {
		return fmt.Errorf("load round %d: %w", targetRound, err)
	}
	replayer := &Replayer{Runtime: rt, Rec: rec}
	for i := 0; i < localIdx; i++ {
		if rt.Game.Phase == engine.PhaseGameOver {
			return nil
		}
		if err := replayer.Step(targetRound, i); err != nil {
			return fmt.Errorf("step round=%d local=%d: %w", targetRound, i, err)
		}
	}
	// Advance out of PhaseRoundStart if no in-round actions ran — otherwise
	// callers observing the view see the pre-round_start state where
	// round_num and the dice pool are stale. Fires round_start hooks so
	// dice roll, hand draws and round_num increment apply.
	if rt.Game.Phase == engine.PhaseRoundStart {
		rt.Game.GetLegalActions()
	}
	return nil
}
