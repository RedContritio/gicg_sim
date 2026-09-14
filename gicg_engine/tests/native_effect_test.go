package tests

import (
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestNativeEffect_ResumesThroughRuntimeClone(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客", "刻师傅", "猫咪"})
	g := env.G
	marker := g.CreateCounter(0, 0, 10)
	frame := engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill}
	result := g.ExecuteEffect(frame, func(g *engine.Game) {
		g.WriteCounter(marker, engine.OpAdd, 1)
		g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
		g.DrainDeferred()
		g.WriteCounter(marker, engine.OpAdd, g.Players[1].ActiveChar+1)
	})
	if result != engine.StepNeedTarget || g.Counters[marker].Value != 1 {
		t.Fatal("native effect did not stop at input")
	}
	for _, choice := range []int{0, 1, 0} {
		branch := env.RT.Clone().Game
		branch.StepTarget(choice)
		if branch.Counters[marker].Value != choice+3 || branch.PendingAction != nil || !branch.IsQuiescent() {
			t.Fatal("native continuation did not preserve remaining effects")
		}
	}
	if g.Counters[marker].Value != 1 || g.PendingAction == nil {
		t.Fatal("native clone changed its source")
	}
}

func TestNativeEffect_UnmanagedInputFailsInsteadOfDroppingWork(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客", "刻师傅"})
	g := env.G
	marker := g.CreateCounter(0, 0, 10)
	var recovered any
	func() {
		defer func() { recovered = recover() }()
		g.PushEvent(engine.EventFrame{Player: 0})
		defer g.PopEvent()
		g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
		g.Defer(func(g *engine.Game) { g.WriteCounter(marker, engine.OpAdd, 1) })
		g.DrainDeferred()
		g.WriteCounter(marker, engine.OpAdd, 2)
	}()
	err, ok := recovered.(*engine.RuleError)
	if !ok || !strings.Contains(err.Error(), "ExecuteEffect") || g.Failure != err || g.Counters[marker].Value != 0 {
		t.Fatalf("unmanaged input was not rejected before later work: %v", recovered)
	}
}

func TestNativeEffect_NoChoiceIsAnErrorAndTerminalNeedsNoChoice(t *testing.T) {
	for _, terminal := range []bool{false, true} {
		env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
		g := env.G
		var recovered any
		func() {
			defer func() { recovered = recover() }()
			g.ExecuteEffect(engine.EventFrame{Player: 0}, func(g *engine.Game) {
				g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
				if terminal {
					g.SetWinner(0)
				}
			})
		}()
		if terminal {
			if recovered != nil || g.PendingAction != nil || g.Phase != engine.PhaseGameOver {
				t.Fatalf("terminal game asked for replacement: %v", recovered)
			}
		} else {
			err, ok := recovered.(*engine.RuleError)
			if !ok || !strings.Contains(err.Error(), "no legal replacement") {
				t.Fatalf("unanswerable input was not rejected: %v", recovered)
			}
		}
	}
}
