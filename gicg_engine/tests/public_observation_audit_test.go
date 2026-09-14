package tests

import (
	engine "gicg_mono/gicg_engine"
	"reflect"
	"testing"
)

func TestPublicDecisionStateVisibleWithoutBuffs(t *testing.T) {
	for _, p := range []int{0, 1} {
		e := currentCardGame(t, p)
		if len(e.G.Buffs) != 0 {
			t.Fatal("fixture must have no buffs")
		}
		base := e.G.BuildDynamicObs(p)
		snap := e.G.SnapshotPooled()
		defer engine.ReleaseSnap(snap)
		cases := []struct {
			name  string
			edit  func()
			field int
			want  int32
		}{
			{"own end", func() { e.G.Players[p].DeclaredEnd = true }, 3, 1},
			{"enemy end", func() { e.G.Players[1-p].DeclaredEnd = true }, 4, 1},
			{"own first", func() { e.G.FirstEnd = p }, 5, 0},
			{"enemy first", func() { e.G.FirstEnd = 1 - p }, 5, 1},
			{"round limit", func() { e.G.MaxRounds = 17 }, 6, 17},
			{"forced decision", func() { e.G.PendingAction = &engine.Action{Kind: engine.ActionSwitch, Forced: true, PlayerIdx: p} }, 8, 1},
			{"fixed roll", func() { e.G.FixDice = []int{1, 0, 0, 0, 0, 0, 0, 7} }, 10, 1},
		}
		for _, c := range cases {
			t.Run(c.name, func(t *testing.T) {
				e.G.RestoreFromSnap(snap)
				e.G.MaxRounds = 0
				e.G.FixDice = nil
				c.edit()
				obs := e.G.BuildDynamicObs(p)
				if reflect.DeepEqual(base, obs) || obs[c.field] != c.want {
					t.Fatalf("%s invisible/wrong viewpoint", c.name)
				}
			})
		}
	}
}

func TestObservationDoesNotRevealHiddenIdentityOrRandomState(t *testing.T) {
	e := currentCardGame(t, 0)
	before := e.G.BuildDynamicObs(0)
	e.G.BuffSerial += 1000
	e.G.Rng.Uint64()
	e.G.DeckRngs[1].Uint64()
	if !reflect.DeepEqual(before, e.G.BuildDynamicObs(0)) {
		t.Fatal("internal RNG or lifecycle serial leaked")
	}
	// Enemy hand identities are hidden, while its size is public.
	refs := []int{}
	for id := range e.G.CardNames {
		refs = append(refs, id)
		if len(refs) == 2 {
			break
		}
	}
	e.G.Players[1].Hand = []engine.CardInst{{Ref: refs[0]}}
	before = e.G.BuildDynamicObs(0)
	e.G.Players[1].Hand[0].Ref = refs[1]
	if !reflect.DeepEqual(before, e.G.BuildDynamicObs(0)) {
		t.Fatal("enemy hand identity leaked")
	}
	e.G.Players[1].Hand = append(e.G.Players[1].Hand, engine.CardInst{Ref: refs[0]})
	if reflect.DeepEqual(before, e.G.BuildDynamicObs(0)) {
		t.Fatal("enemy hand size invisible")
	}
}

func TestCounterObservationOverflowFailsLoud(t *testing.T) {
	for _, static := range []bool{false, true} {
		t.Run(map[bool]string{true: "static", false: "dynamic"}[static], func(t *testing.T) {
			e := currentCardGame(t, 0)
			for i := 0; i < engine.ObsGlobalSlots+1; i++ {
				e.G.CreateCounter(0, 0, 1)
			}
			defer func() {
				if recover() == nil {
					t.Fatal("counter state silently truncated")
				}
			}()
			if static {
				e.G.BuildStaticObs()
			} else {
				e.G.BuildDynamicObs(0)
			}
		})
	}
}

func TestEndingStateChangesTransitionAndObservation(t *testing.T) {
	e := currentCardGame(t, 0)
	a, b := e.RT.Clone(), e.RT.Clone()
	b.Game.Players[1].DeclaredEnd = true
	b.Game.FirstEnd = 1
	left, right := a.Game.BuildDynamicObs(0), b.Game.BuildDynamicObs(0)
	if !reflect.DeepEqual(left[:3], right[:3]) || !reflect.DeepEqual(left[engine.ObsMetaSize:], right[engine.ObsMetaSize:]) {
		t.Fatal("fixture should isolate the formerly hidden public state")
	}
	if reflect.DeepEqual(left, right) {
		t.Fatal("different transition states still alias in NN observation")
	}
	index := -1
	for i, action := range a.Game.GetLegalActions() {
		if action.Kind == engine.ActionSkill {
			index = i
			break
		}
	}
	if index < 0 {
		t.Fatal("missing skill")
	}
	a.Game.Step(index)
	b.Game.Step(index)
	if a.Game.Turn != 1 || b.Game.Turn != 0 {
		t.Fatal("fixture did not exercise declared-end turn behavior")
	}
}
