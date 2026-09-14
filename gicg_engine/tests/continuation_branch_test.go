package tests

import (
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestContinuation_RepeatedInputsPreserveSampledBranches(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客", "刻师傅", "赤蝶"})
	g := env.G
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 8})
	first := g.CreateCounter(0, 0, 100000)
	second := g.CreateCounter(0, 0, 100000)
	g.Hooks.Register(engine.Hook{Type: engine.HookSkillUse, Priority: -100,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.ActorPlayer != 0 {
				return
			}
			g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
			g.Defer(func(g *engine.Game) {
				g.WriteCounter(first, engine.OpSet, g.Rng.Intn(100000))
				g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
				g.Defer(func(g *engine.Game) { g.WriteCounter(second, engine.OpSet, g.Rng.Intn(100000)) })
			})
		}})
	if g.Step(env.FindAction(engine.ActionSkill, "枪")) != engine.StepNeedTarget {
		t.Fatal("first input was not requested")
	}
	root := g.SnapshotPooled()
	defer engine.ReleaseSnap(root)
	for _, seed := range []int64{73, 99, 73} {
		branch := env.RT.Clone().Game
		branch.SetSimulationSeed(seed)
		branch.SetPlayerHand(0, []int{1, 2})
		branch.SetPlayerDeck(1, []int{3, 4, 5})
		wantFirst := branch.Rng.Clone().Intn(100000)
		if branch.Step(0) != engine.StepNeedTarget || branch.Counters[first].Value != wantFirst || branch.Counters[second].Value != 0 {
			t.Fatal("first choice lost branch RNG or advanced beyond the second input")
		}
		middle := branch.SnapshotPooled()
		for _, nextSeed := range []int64{11, 22, 11} {
			branch.RestoreFromSnap(middle)
			branch.SetSimulationSeed(nextSeed)
			branch.SetPlayerHand(0, []int{2})
			branch.SetPlayerDeck(1, []int{5, 4})
			wantSecond := branch.Rng.Clone().Intn(100000)
			if branch.StepTarget(1) == engine.StepNeedTarget || branch.PendingAction != nil {
				t.Fatal("second input did not complete")
			}
			if branch.Counters[first].Value != wantFirst || branch.Counters[second].Value != wantSecond {
				t.Fatal("reconstruction overwrote a sampled random outcome")
			}
			if !reflect.DeepEqual(branch.Players[0].Hand, []engine.CardInst{{Ref: 2, DrawnAtRound: branch.Round}}) ||
				!reflect.DeepEqual(branch.Players[1].Deck, []engine.CardInst{{Ref: 5}, {Ref: 4}}) {
				t.Fatal("reconstruction overwrote a sampled hand/deck")
			}
			if branch.Turn != 1 || branch.Players[1].ActiveChar != 2 || !branch.IsQuiescent() {
				t.Fatal("continuation did not finish at the expected decision boundary")
			}
		}
		engine.ReleaseSnap(middle)
		if g.Counters[first].Value != 0 || g.Counters[second].Value != 0 || g.PendingAction == nil || len(g.Players[0].Hand) != 0 {
			t.Fatal("resuming clone changed the waiting source")
		}
	}
	// Waiting continuations share immutable reconstruction data; each clone
	// owns its cursor, gameplay and rebuilt stack even when resumed concurrently.
	results := make(chan bool, 4)
	for worker := 0; worker < 4; worker++ {
		branchRT := env.RT.Clone()
		go func() {
			branch := branchRT.Game
			branch.StepTarget(0)
			branch.StepTarget(1)
			results <- branch.PendingAction == nil && branch.Turn == 1 && branch.IsQuiescent()
		}()
	}
	for worker := 0; worker < 4; worker++ {
		if !<-results {
			t.Fatal("concurrent clone did not finish")
		}
	}
	g.RestoreFromSnap(root)
	g.StepTarget(0)
	g.StepTarget(1)
	counts := map[string]int{}
	for _, entry := range g.Log.Entries {
		counts[entry.Type]++
	}
	if counts["action_skill"] != 1 || counts["action_switch"] != 2 || counts["damage"] != 1 {
		t.Fatalf("reconstruction duplicated or lost log events: %v", counts)
	}
}
