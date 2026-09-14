package mcts

import (
	engine "gicg_mono/gicg_engine"
)

// LegalActionIds extracts the ActionId list from the game's current
// legal actions. Mirrors training/mcts.py::legal_ids_from_env: walks
// each legal Action, builds a (kind, subject, aux, target_p,
// target_c, payment_8d) identity.
//
// The identity matches what GameGetActionIdentities + the Python
// build_action_id function produce — so ActionIds from Go MCTS align
// with Python MCTS when running parity tests.
func LegalActionIds(g *engine.Game) []ActionId {
	actions := g.GetLegalActions()
	ids := make([]ActionId, len(actions))
	for i, a := range actions {
		ids[i] = actionToId(g, a)
	}
	return ids
}

// ActionRefs builds the (N_legal × 3) [kind, hook_idx, char_idx]
// array the policy head consumes. Mirrors capi.GameGetActionRefs
// so Go-side MCTS eval requests deliver the same refs to the
// network as Python's env.get_action_refs().
//
// Returned as a flat N*3 []int32 in the same order as
// GetLegalActions(). Caller owns the slice.
func ActionRefs(g *engine.Game) []int32 {
	actions := g.GetLegalActions()
	out := make([]int32, len(actions)*3)
	if len(actions) == 0 {
		return out
	}
	rawToActive := g.BuildRawToActiveHookIdx()
	for i, a := range actions {
		hookIdx := int32(-1)
		charIdx := int32(engine.ActionCharRef(a))
		switch a.Kind {
		case engine.ActionReroll:
			hookIdx = int32(a.Index) // quantity, not a hook for this action kind
		case engine.ActionSkill:
			pi := a.PlayerIdx
			ci := g.Players[pi].ActiveChar
			if rawID, ok := g.CanonicalSkillHooks[[3]int{pi, ci, a.Index}]; ok {
				if ai, ok2 := rawToActive[rawID]; ok2 {
					hookIdx = int32(ai)
				}
			}
		case engine.ActionCard, engine.ActionTune:
			pi := a.PlayerIdx
			ref := -1
			if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
				ref = g.Players[pi].Hand[a.Index].Ref
			}
			if ref >= 0 {
				if rawID, ok := g.CanonicalCardHooks[ref]; ok {
					if ai, ok2 := rawToActive[rawID]; ok2 {
						hookIdx = int32(ai)
					}
				}
			}
		case engine.ActionSwitch:
			charIdx = int32(a.Index)
		}
		out[i*3+0] = int32(a.Kind)
		out[i*3+1] = hookIdx
		out[i*3+2] = charIdx
	}
	return out
}

// actionToId extracts the stable MCTS identity for a single Action.
// Duplicates the switch logic in gicg_engine/capi/capi.go::GameGetActionIdentities
// to keep that capi function as the C-facing export while gicg_mcts
// works in native Go.
func actionToId(g *engine.Game, a engine.Action) ActionId {
	kind := int32(a.Kind)
	var subject, aux, tgtP, tgtC int32 = -1, -1, -1, -1

	switch a.Kind {
	case engine.ActionReroll:
		subject, aux = int32(a.Index), int32(a.RerollColor)
	case engine.ActionSkill:
		subject = int32(a.Index)

	case engine.ActionCard:
		pi := a.PlayerIdx
		if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
			subject = int32(g.Players[pi].Hand[a.Index].Ref)
		}
		if a.HasTarget {
			tgtP = int32(a.TargetPlayer)
			tgtC = int32(a.TargetChar)
		}
		if a.HasBuffTarget {
			aux, tgtP, tgtC = int32(a.TargetBuff), int32(a.TargetPlayer), -1
		}
		if a.HasSupportTarget {
			aux, tgtP, tgtC = int32(engine.ObsBuffRows+a.TargetSupport), int32(a.PlayerIdx), -1
		}

	case engine.ActionSwitch:
		subject = int32(a.Index)

	case engine.ActionTune:
		pi := a.PlayerIdx
		if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
			subject = int32(g.Players[pi].Hand[a.Index].Ref)
		}
		aux = int32(a.TuneSourceColor)

	case engine.ActionEndTurn:
		// all -1
	}

	var payment [8]int32
	for c := 0; c < 8 && c < len(a.DicePayment); c++ {
		payment[c] = int32(a.DicePayment[c])
	}

	return ActionId{
		Kind:    kind,
		SubA:    subject,
		SubB:    aux,
		SubC:    tgtP,
		SubD:    tgtC,
		Payment: payment,
	}
}
