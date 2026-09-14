package tests

import (
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func drawStreams(g *engine.Game) []uint64 {
	var out []uint64
	for i := 0; i < 40; i++ {
		out = append(out, g.Rng.Uint64(), g.DeckRngs[0].Uint64(), g.DeckRngs[1].Uint64())
	}
	return out
}

func TestRandom_SnapshotsDoNotConsumeSourceAndRestoreExactly(t *testing.T) {
	for _, pooled := range []bool{false, true} {
		t.Run(map[bool]string{false: "full", true: "pooled"}[pooled], func(t *testing.T) {
			env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
			control := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
			g := env.G
			var restore func()
			if pooled {
				s := g.SnapshotPooled()
				defer engine.ReleaseSnap(s)
				restore = func() { g.RestoreFromSnap(s) }
			} else {
				s := g.DeepCopy()
				restore = func() { g.RestoreFrom(s) }
			}
			want := drawStreams(control.G)
			if !reflect.DeepEqual(drawStreams(g), want) {
				t.Fatal("snapshot changed live random streams")
			}
			for i := 0; i < 3; i++ {
				restore()
				if !reflect.DeepEqual(drawStreams(g), want) {
					t.Fatal("restore failed to reproduce random streams")
				}
			}
		})
	}
}

func TestRandom_CloneIsolationAndExplicitSimulationSeed(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	control := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	a, b := env.RT.Clone(), env.RT.Clone()
	a.Game.SetSimulationSeed(100)
	b.Game.SetSimulationSeed(101)
	if reflect.DeepEqual(drawStreams(a.Game), drawStreams(b.Game)) {
		t.Fatal("simulation streams did not separate")
	}
	if !reflect.DeepEqual(drawStreams(env.G), drawStreams(control.G)) {
		t.Fatal("simulation changed live streams")
	}
}

func TestLifecycle_RepeatedBranchExecution(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶", "墨客"}, []string{"刻师傅", "猫咪"})
	g := env.G
	s := g.SnapshotPooled()
	defer engine.ReleaseSnap(s)
	run := func() []int32 {
		for i := 0; i < 50 && g.Phase != engine.PhaseGameOver; i++ {
			actions := g.GetLegalActions()
			if len(actions) == 0 {
				t.Fatal("nonterminal state has no actions")
			}
			g.Step((i*7 + 3) % len(actions))
		}
		return append([]int32(nil), g.BuildDynamicObs(0)...)
	}
	want := run()
	for i := 0; i < 3; i++ {
		g.RestoreFromSnap(s)
		if !reflect.DeepEqual(run(), want) {
			t.Fatal("same branch changed after restore")
		}
	}
}
