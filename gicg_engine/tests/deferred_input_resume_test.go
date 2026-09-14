package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// The second effect must resolve against the chosen replacement, not the dead
// active character. This exercises the complete skill caller, not only Drain.
func TestDeferredInput_SuspendsSkillUntilReplacement(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客", "刻师傅", "赤蝶"})
	g := env.G
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 8})
	marker := g.CreateCounter(0, 0, 100)
	hp0 := env.RT.Chars.BySlot[1][0].HPCounterID
	g.Counters[hp0].Value = 1
	hpIDs := []int{hp0, env.RT.Chars.BySlot[1][1].HPCounterID, env.RT.Chars.BySlot[1][2].HPCounterID}
	g.Hooks.Register(engine.Hook{Type: engine.HookSkillUse, Priority: -100,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.ActorPlayer != 0 {
				return
			}
			g.Defer(func(g *engine.Game) {
				g.WriteCounter(marker, engine.OpAdd, 1)
				hp := hpIDs[g.Players[1].ActiveChar]
				g.DealDamage(hp, engine.ElemPhysical, 1, engine.DamageOpts{ActorPlayer: 0, ActorChar: 0})
			})
		}})
	idx := env.FindAction(engine.ActionSkill, "枪")
	if idx < 0 {
		t.Fatal("missing fixture skill")
	}
	result := g.Step(idx)
	if result != engine.StepNeedTarget || g.PendingAction == nil || g.Counters[marker].Value != 0 || g.Turn != 0 {
		t.Fatalf("skill advanced past required input: result=%v pending=%v marker=%d turn=%d",
			result, g.PendingAction, g.Counters[marker].Value, g.Turn)
	}
	if !g.IsQuiescent() {
		t.Fatal("waiting state cannot be snapshotted")
	}
	root := g.SnapshotPooled()
	defer engine.ReleaseSnap(root)
	for _, choice := range []int{0, 1, 0} {
		g.RestoreFromSnap(root)
		g.StepTarget(choice)
		if g.PendingAction != nil || g.Players[1].ActiveChar != choice+1 || g.Counters[marker].Value != 1 || g.Turn != 1 {
			t.Fatalf("resume choice=%d did not complete exactly once", choice)
		}
		for slot := 1; slot < 3; slot++ {
			want := root.Counters[hpIDs[slot]].Value
			if slot == choice+1 {
				want--
			}
			if got := g.Counters[hpIDs[slot]].Value; got != want {
				t.Fatalf("choice=%d slot=%d HP=%d want=%d", choice, slot, got, want)
			}
		}
	}
}

func TestDeferredInput_SuspendsRoundEndUntilReplacement(t *testing.T) {
	defer func() {
		if err := recover(); err != nil {
			t.Errorf("round-end input caused a panic instead of a resumable decision: %v", err)
		}
	}()
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客", "刻师傅"})
	g := env.G
	marker := g.CreateCounter(0, 0, 10)
	g.Hooks.Register(engine.Hook{Type: engine.HookRoundEnd, OwnerPlayer: 0,
		Fn: func(g *engine.Game, _ *engine.EventContext) {
			g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
			g.Defer(func(g *engine.Game) { g.WriteCounter(marker, engine.OpAdd, 1) })
		}})
	g.Hooks.Register(engine.Hook{Type: engine.HookRoundEndFinal, OwnerPlayer: 0,
		Fn: func(g *engine.Game, _ *engine.EventContext) { g.WriteCounter(marker, engine.OpAdd, 2) }})
	g.Step(env.FindAction(engine.ActionEndTurn, ""))
	g.Step(env.FindAction(engine.ActionEndTurn, ""))
	if g.Phase != engine.PhaseRoundEnd || g.PendingAction == nil || g.Counters[marker].Value != 0 {
		t.Fatalf("round advanced past input: phase=%v pending=%v marker=%d", g.Phase, g.PendingAction, g.Counters[marker].Value)
	}
	if len(g.GetLegalActions()) != 1 {
		t.Fatal("round-end replacement choice is unavailable")
	}
	g.StepTarget(0)
	if g.Phase != engine.PhaseRoundStart || g.PendingAction != nil || g.Counters[marker].Value != 3 {
		t.Fatal("remaining round-end effects did not complete exactly once")
	}
}

func TestDeferredInput_NewRoundQueryDoesNotRestartWaitingRound(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客", "刻师傅"})
	g := env.G
	marker := g.CreateCounter(0, 0, 10)
	g.Hooks.Register(engine.Hook{Type: engine.HookRoundStart, OwnerPlayer: 0,
		Fn: func(g *engine.Game, _ *engine.EventContext) {
			g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
			g.Defer(func(g *engine.Game) { g.WriteCounter(marker, engine.OpAdd, 1) })
		}})
	g.Step(env.FindAction(engine.ActionEndTurn, ""))
	g.Step(env.FindAction(engine.ActionEndTurn, ""))
	for query := 0; query < 3; query++ {
		if len(g.GetLegalActions()) != 1 || g.Round != 2 || g.Counters[marker].Value != 0 {
			t.Fatal("repeated action query restarted or completed a waiting round")
		}
	}
	g.Step(0)
	if g.PendingAction != nil || g.Round != 2 || g.Phase != engine.PhaseAction || g.Counters[marker].Value != 1 {
		t.Fatal("round-start continuation did not finish once")
	}
}
