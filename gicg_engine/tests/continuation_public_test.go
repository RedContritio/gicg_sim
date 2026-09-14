package tests

import (
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

func causeRow(t *testing.T, g *engine.Game, p int) []int32 {
	t.Helper()
	for _, r := range entityRows(g, p, engine.EntityExecutionFrame) {
		if r[8] == engine.ProgramPublicCause {
			return r
		}
	}
	t.Fatal("public continuation cause missing")
	return nil
}

func TestPublicRoundStageAndRepeatedChoiceOrdinal(t *testing.T) {
	e := NewGame(t, []string{"赤蝶"}, []string{"墨客", "赤蝶", "刻师傅"})
	g := e.G
	g.Hooks.Register(engine.Hook{Type: engine.HookRoundEnd, OwnerPlayer: 0,
		Fn: func(g *engine.Game, _ *engine.EventContext) {
			g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
			g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
		}})
	g.Step(e.FindAction(engine.ActionEndTurn, ""))
	g.Step(e.FindAction(engine.ActionEndTurn, ""))
	first := causeRow(t, g, 1)
	if first[4] != engine.CauseRound || first[5] != int32(engine.HookRoundEnd) || first[7] != -1 || first[9] != 0 {
		t.Fatal("round origin lost or invented a private hook", first)
	}
	branch := e.RT.Clone().Game
	branch.StepTarget(0)
	if causeRow(t, branch, 1)[9] != 1 || causeRow(t, g, 1)[9] != 0 {
		t.Fatal("public choice ordinal lost/aliased")
	}
}

func TestViewCounterStatusesHaveStableOrder(t *testing.T) {
	e := currentCardGame(t, 0)
	g := e.G
	for id := range g.Counters {
		if g.GetCounterChar(id) == [2]int{0, 0} && g.Counters[id].Max > 0 {
			g.Counters[id].Value = 1
		}
	}
	view := record.ExportView(e.RT)
	if len(view.Players[0].Chars[0].Statuses) < 3 {
		t.Fatal("fixture needs several status counters")
	}
	for repeat := 0; repeat < 20; repeat++ {
		if !reflect.DeepEqual(view, record.ExportView(e.RT.Clone())) {
			t.Fatal("map iteration leaked into public view order")
		}
	}
}

func TestPublicCauseDistinguishesEqualBoardDifferentRemainingDamage(t *testing.T) {
	e := currentCardGame(t, 0, []string{"赤蝶"}, []string{"墨客", "赤蝶", "刻师傅"})
	g := e.G
	blank := e.RT.Cards.ByName["碌碌无为"].Ref
	shard := e.RT.Cards.ByName["测试卡_碎片"].Ref
	hp := e.RT.Chars.BySlot[1][0].HPCounterID
	g.Counters[hp].Value = 1
	e.SetDice(0, map[int]int{engine.DiceColorOmni: 8})
	g.SetPlayerHand(0, []int{blank, shard})
	// Both public cards first deal the SAME lethal hit. Once the target is
	// chosen only the shard's real DSL body deals one additional damage.
	g.Hooks.Register(engine.Hook{Type: engine.HookCardPlay, Priority: 1000,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.CardRef == blank || ctx.CardRef == shard {
				g.DealDamage(hp, engine.ElemPhysical, 1, engine.DamageOpts{ActorPlayer: 0, ActorChar: 0})
			}
		}})
	left, right := e.RT.Clone(), e.RT.Clone()
	for i, rt := range []*engine.Game{left.Game, right.Game} {
		ref := []int{blank, shard}[i]
		index := -1
		for j, action := range rt.GetLegalActions() {
			if action.Kind == engine.ActionCard && rt.Players[0].Hand[action.Index].Ref == ref {
				index = j
				break
			}
		}
		if index < 0 || rt.Step(index) != engine.StepNeedTarget {
			t.Fatal("fixture did not suspend")
		}
		// Controlled state pair: discard multisets deliberately normalized.
		// The observer cannot see which card remains in the enemy hand.
		rt.Players[0].Discard = []engine.CardInst{{Ref: blank}, {Ref: shard}}
	}
	a, b := left.Game.BuildDynamicObs(1), right.Game.BuildDynamicObs(1)
	if reflect.DeepEqual(a, b) || causeRow(t, left.Game, 1)[7] == causeRow(t, right.Game, 1)[7] {
		t.Fatal("remaining public program invisible")
	}
	for _, obs := range [][]int32{a, b} {
		start := len(obs) - engine.ObsBuffSlots
		for i := start; i < len(obs); i += engine.ObsBuffFields {
			if obs[i] == 1 && obs[i+12] == engine.EntityExecutionFrame && obs[i+8] == engine.ProgramPublicCause {
				clear(obs[i : i+engine.ObsBuffFields])
			}
		}
	}
	if !reflect.DeepEqual(a, b) {
		t.Fatal("fixture has other observable differences")
	}
	left.Game.StepTarget(0)
	right.Game.StepTarget(0)
	replacementHP := e.RT.Chars.BySlot[1][1].HPCounterID
	if left.Game.Counters[replacementHP].Value != right.Game.Counters[replacementHP].Value+1 {
		t.Fatal("fixture must have different remaining effects")
	}
}

func TestPublicCauseSurvivesCloneAndHidesPrivateBranchState(t *testing.T) {
	e := currentCardGame(t, 0, []string{"赤蝶"}, []string{"墨客", "赤蝶", "刻师傅"})
	g := e.G
	g.Counters[e.RT.Chars.BySlot[1][0].HPCounterID].Value = 1
	g.Step(e.FindAction(engine.ActionSkill, "枪"))
	row := causeRow(t, g, 1)
	if row[1] != 1 || row[2] != 0 || row[4] != engine.CauseSkill || row[7] < 0 || row[3] != 0 {
		t.Fatal("wrong source/perspective or false completeness", row)
	}
	branch := e.RT.Clone().Game
	before := branch.BuildDynamicObs(1)
	ref := e.RT.Cards.ByName["碌碌无为"].Ref
	branch.SetPlayerHand(0, []int{ref})
	base := branch.BuildDynamicObs(1)
	branch.SetPlayerHand(0, []int{e.RT.Cards.ByName["测试卡_碎片"].Ref})
	branch.SetSimulationSeed(999)
	if !reflect.DeepEqual(base, branch.BuildDynamicObs(1)) || !reflect.DeepEqual(row, causeRow(t, branch, 1)) {
		t.Fatal("private hand identity or RNG leaked")
	}
	if !reflect.DeepEqual(before, g.BuildDynamicObs(1)) {
		t.Fatal("clone modified source")
	}
	snap := branch.SnapshotPooled()
	defer engine.ReleaseSnap(snap)
	branch.StepTarget(1)
	branch.RestoreFromSnap(snap)
	if !reflect.DeepEqual(row, causeRow(t, branch, 1)) {
		t.Fatal("snapshot lost public cause")
	}
}
