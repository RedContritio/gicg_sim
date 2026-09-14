package tests

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

// Independent oracle: SID -> raw counter via the engine permutation, rather
// than reproducing the observation bucket ordering.
func assertCanonicalCounterView(t *testing.T, g *engine.Game) {
	t.Helper()
	static := g.BuildStaticObs()
	kinds := g.Extra.(engine.ObservationReferenceResolver).ObservationReferenceKinds()
	n := 2*engine.ObsMaxChars*engine.ObsCharSlots + 2*engine.ObsPlayerSlots + engine.ObsGlobalSlots
	for p := 0; p < 2; p++ {
		obs := g.BuildDynamicObs(p)
		if obs[18] != int32(p) {
			t.Fatal("observer missing")
		}
		for slot := 0; slot < n; slot++ {
			meta := static[slot*3 : slot*3+3]
			if meta[0] == 0 && meta[1] == 0 && meta[2] == 0 {
				continue
			}
			sid := int(meta[2])
			raw := sid
			if g.CounterPerm != nil {
				raw = g.CounterPerm[sid]
			}
			want := g.Counters[raw].Value
			if kinds[raw] != 0 {
				if want >= 0 {
					want = 1
				} else {
					want = 0
				}
			}
			if got := int(obs[engine.ObsMetaSize+slot]); got != want {
				t.Fatalf("P%d slot%d SID%d got%d want%d", p, slot, sid, got, want)
			}
		}
	}
}

func TestCounterPerspectiveAsymmetricTeams(t *testing.T) {
	e := currentCardGame(t, 0, []string{"赤蝶"}, []string{"墨客", "赤蝶"})
	for p, hp := range []int{3, 11} {
		e.G.Counters[e.RT.Chars.BySlot[p][0].HPCounterID].Value = hp
	}
	assertCanonicalCounterView(t, e.G)
	// Reference identity and ordinary quantities must share the SAME SID basis.
	auditPlay(t, e, 0, "铁枪")
	assertCanonicalCounterView(t, e.G)
	clone := e.RT.Clone().Game
	assertCanonicalCounterView(t, clone)
}

func TestCounterPerspectiveForcedSwitch(t *testing.T) {
	e := currentCardGame(t, 0, []string{"赤蝶"}, []string{"墨客", "赤蝶"})
	g := e.G
	g.Counters[e.RT.Chars.BySlot[1][0].HPCounterID].Value = 1
	idx := e.FindAction(engine.ActionSkill, "枪")
	if idx < 0 || g.Step(idx) != engine.StepNeedTarget {
		t.Fatal("fixture did not force switch")
	}
	if g.Turn != 0 || g.ActingPlayer() != 1 {
		t.Fatal("fixture must separate turn and decision-maker")
	}
	frames := entityRows(g, 1, engine.EntityExecutionFrame)
	if kind, waiting := g.SuspensionKind(); !waiting || kind != engine.ProgramReplayBridge ||
		len(frames) != 2 || frames[0][3] != 0 || frames[0][8] != int32(engine.ProgramReplayBridge) {
		t.Fatal("nested damage must expose an incomplete replay bridge", frames)
	}
	if _, err := g.ExportCheckpoint(); err == nil {
		t.Fatal("nested Go/DSL continuation cannot yet be serialized")
	}
	assertCanonicalCounterView(t, g)
	obs := g.BuildDynamicObs(g.ActingPlayer())
	if obs[18] != 1 || obs[2] != 0 || obs[8] != 1 {
		t.Fatal("forced observer/turn metadata", obs[:engine.ObsMetaSize])
	}
	snap := g.SnapshotPooled()
	defer engine.ReleaseSnap(snap)
	g.StepTarget(0)
	assertCanonicalCounterView(t, g)
	g.RestoreFromSnap(snap)
	assertCanonicalCounterView(t, g)
}
