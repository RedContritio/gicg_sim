package mcts

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"time"
)

// Rollout support: determinization apply, child-set management
// (hasNewActions / selectAndMap / addNewActionsUniform / D1 uniform),
// random rollout, eval request builder, profile timing helpers, detRNG.

func applyDeterminization(rt *interp.Runtime, d *Determinization) {
	if d.Opponent < 0 || d.Opponent > 1 {
		return
	}
	pi := int(d.Opponent)

	if d.Hand != nil {
		refs := make([]int, len(d.Hand))
		for i, r := range d.Hand {
			refs[i] = int(r)
		}
		rt.Game.SetPlayerHand(pi, refs)
	}
	if d.Deck != nil {
		refs := make([]int, len(d.Deck))
		for i, r := range d.Deck {
			refs[i] = int(r)
		}
		rt.Game.SetPlayerDeck(pi, refs)
	}
	if d.Dice != nil && len(d.Dice) == engine.DiceColorCount {
		var counts [engine.DiceColorCount]int
		for c := 0; c < engine.DiceColorCount; c++ {
			counts[c] = int(d.Dice[c])
		}
		rt.SetPlayerDice(pi, counts)
	}
}

func hasNewActions(node *Node, legalIds []ActionId) bool {
	node.BeginRead()
	defer node.EndRead()
	for _, lid := range legalIds {
		found := false
		for _, aid := range node.actions {
			if aid.Equal(lid) {
				found = true
				break
			}
		}
		if !found {
			return true
		}
	}
	return false
}

func selectAndMap(
	pool *Pool, node *Node, legalIds []ActionId, cPuct float32,
) (childIdx int32, action ActionId, stepIdx int, err error) {
	node.BeginRead()
	children := node.children
	actions := node.actions

	legalMask := make([]bool, len(actions))
	for _, lid := range legalIds {
		for i, aid := range actions {
			if aid.Equal(lid) {
				legalMask[i] = true
				break
			}
		}
	}
	for i, ok := range legalMask {
		if ok {
			pool.Get(children[i]).NAvail.Add(1)
		}
	}
	slot := SelectChild(pool, node, legalMask, cPuct)
	childIdx = children[slot]
	action = actions[slot]
	node.EndRead()

	stepIdx = -1
	for i, lid := range legalIds {
		if lid.Equal(action) {
			stepIdx = i
			break
		}
	}
	if stepIdx < 0 {
		err = fmt.Errorf(
			"PUCT chose action not in current legal set — " +
				"descend invariant violated")
	}
	return
}

// addNewActionsUniform appends children for actions in legalIds
// that are not yet in node.actions, using uniform prior
// (1 / total_legal). No eval RPC — matches Python async's
// _descend_with_vl behavior at D1. Safe under
// concurrent access: the second-check inside LockForAppend prevents
// races where two goroutines append the same action.
// addNewActionsUniform appends uniform-prior children for any action
// in legalIds that the node doesn't already have. Returns the number
// of actions actually added (0 if all were already present — the
// outer caller can use this to distinguish the "hasNewActions
// flagged but the race inside LockForAppend found they'd been added
// meanwhile" case from a real D1 event).
func addNewActionsUniform(pool *Pool, node *Node, legalIds []ActionId) int {
	existing, existingActions := node.LockForAppend()
	defer node.UnlockAfterAppend()

	existingSet := make(map[ActionId]struct{}, len(existingActions))
	for _, aid := range existingActions {
		existingSet[aid] = struct{}{}
	}

	uniform := float32(1) / float32(len(legalIds))
	var newChildren []int32
	var newActions []ActionId
	for _, lid := range legalIds {
		if _, ok := existingSet[lid]; ok {
			continue
		}
		idx, child := pool.Alloc()
		child.Prior = uniform
		child.Turn = -1
		newChildren = append(newChildren, idx)
		newActions = append(newActions, lid)
	}
	_ = existing
	if len(newChildren) > 0 {
		node.AppendUnlocked(newChildren, newActions)
	}
	return len(newChildren)
}

func randomRollout(rt *interp.Runtime, seed uint64, maxSteps int) (int, int) {
	g := rt.Game
	rng := newDetRNG(seed)
	steps := 0
	for i := 0; i < maxSteps; i++ {
		if g.Phase == engine.PhaseGameOver {
			break
		}
		rt.CurrentContextPlayer = int(g.Turn)
		actions := g.GetLegalActions()
		if len(actions) == 0 {
			break
		}
		idx := int(rng.Uint64() % uint64(len(actions)))
		if g.HasPending() {
			g.StepTarget(idx)
		} else {
			g.Step(idx)
		}
		steps++
	}
	if g.Phase == engine.PhaseGameOver {
		return g.Winner, steps
	}
	return -1, steps
}

func buildEvalRequest(g *engine.Game, input *SearchInput, legalIds []ActionId) EvalRequest {
	perspective := int(g.Turn)
	obs := g.BuildDynamicObs(perspective)

	// ActionRefs reads from engine.GetLegalActions() directly. With the
	// ExpandUnionK removal this is always consistent with legalIds
	// (both derive from the same LegalActionIds source).
	refs := ActionRefs(g)

	n := len(legalIds)
	pay := make([]int32, n*8)
	for i, aid := range legalIds {
		for c := 0; c < 8; c++ {
			pay[i*8+c] = aid.Payment[c]
		}
	}
	return EvalRequest{
		WorkerID: input.WorkerID,
		GameID:   input.GameID,
		DynObs:   obs,
		Refs:     refs,
		Pay:      pay,
		NLegal:   int32(n),
	}
}

// --- Profile timing helpers ---

func timeIfProf(prof *Profile) time.Time {
	if prof == nil {
		return time.Time{}
	}
	return time.Now()
}

type profField int

const (
	prof_restoreNS profField = iota
	prof_determNS
	prof_evalNS
	prof_rolloutNS
	prof_rolloutExtraNS
	prof_descendNS
	prof_commitNS
	prof_envQueryNS
	prof_envStepNS
)

func addNS(prof *Profile, f profField, start time.Time) {
	if prof == nil || start.IsZero() {
		return
	}
	d := time.Since(start).Nanoseconds()
	switch f {
	case prof_restoreNS:
		prof.RestoreNS.Add(d)
	case prof_determNS:
		prof.DeterminizeNS.Add(d)
	case prof_evalNS:
		prof.EvalNS.Add(d)
	case prof_rolloutNS, prof_rolloutExtraNS:
		prof.RolloutNS.Add(d)
	case prof_descendNS:
		prof.DescendNS.Add(d)
	case prof_commitNS:
		prof.CommitNS.Add(d)
	case prof_envQueryNS:
		prof.EnvQueryNS.Add(d)
	case prof_envStepNS:
		prof.EnvStepNS.Add(d)
	}
}

// detRNG: splitmix64.
type detRNG struct{ state uint64 }

func newDetRNG(seed uint64) *detRNG { return &detRNG{state: seed} }

func (r *detRNG) Uint64() uint64 {
	r.state += 0x9E3779B97F4A7C15
	z := r.state
	z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9
	z = (z ^ (z >> 27)) * 0x94D049BB133111EB
	return z ^ (z >> 31)
}
