package tests

import (
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

func TestContinuation_ReplayIncludesRoundEndChoices(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客", "刻师傅", "猫咪"})
	g := env.G
	g.Hooks.Register(engine.Hook{Type: engine.HookRoundEnd, OwnerPlayer: 0,
		Fn: func(g *engine.Game, _ *engine.EventContext) {
			g.DeferAction(&engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1, Forced: true})
		}})
	env.RT.ResetDynamic(42)
	if err := keepAllRerolls(g); err != nil {
		t.Fatal(err)
	}
	initial, err := record.Parse(record.Export(env.RT))
	if err != nil {
		t.Fatal(err)
	}
	base := record.TotalSteps(initial)
	receiver := env.RT.Clone()
	states := []*engine.Game{g.DeepCopy()}
	g.Step(env.FindAction(engine.ActionEndTurn, ""))
	states = append(states, g.DeepCopy())
	g.Step(env.FindAction(engine.ActionEndTurn, ""))
	states = append(states, g.DeepCopy())
	g.StepTarget(1) // non-default replacement must be preserved in the record
	if err := keepAllRerolls(g); err != nil {
		t.Fatal(err)
	}
	states = append(states, g.DeepCopy())
	rec, err := record.Parse(record.Export(env.RT))
	if err != nil {
		t.Fatal(err)
	}
	if record.TotalSteps(rec) <= base+3 {
		t.Fatalf("lost forced replacement input: steps=%d", record.TotalSteps(rec))
	}
	prefixes := []struct {
		prefix int
		state  int
	}{
		{base + 2, 2},
		{record.TotalSteps(rec), 3},
		{base, 0},
		{base + 1, 1},
		{base + 2, 2},
		{record.TotalSteps(rec), 3},
	}
	for _, tc := range prefixes {
		prefix := tc.prefix
		if err := record.ReplayTo(receiver, rec, prefix); err != nil {
			t.Fatalf("prefix %d: %v", prefix, err)
		}
		got, want := receiver.Game, states[tc.state]
		if got.Phase != want.Phase || got.Round != want.Round || got.Turn != want.Turn ||
			!reflect.DeepEqual(got.Counters, want.Counters) || !reflect.DeepEqual(got.Players, want.Players) ||
			!reflect.DeepEqual(got.PendingAction, want.PendingAction) {
			t.Fatalf("prefix %d differs (phase=%v want=%v)", prefix, got.Phase, want.Phase)
		}
		if prefix == base+2 {
			got.StepTarget(1)
			if err := keepAllRerolls(got); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got.Players, states[3].Players) || !reflect.DeepEqual(got.Counters, states[3].Counters) {
				t.Fatal("replayed waiting prefix lost its continuation")
			}
		}
	}
}
