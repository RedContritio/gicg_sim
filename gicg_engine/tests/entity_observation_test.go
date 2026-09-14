package tests

import (
	engine "gicg_mono/gicg_engine"
	"reflect"
	"testing"
)

func entityRows(g *engine.Game, perspective, kind int) [][]int32 {
	obs := g.BuildDynamicObs(perspective)
	tail := obs[len(obs)-engine.ObsBuffSlots:]
	var result [][]int32
	for i := 0; i < len(tail); i += engine.ObsBuffFields {
		row := tail[i : i+engine.ObsBuffFields]
		if row[0] != 0 && row[12] == int32(kind) {
			result = append(result, row)
		}
	}
	return result
}

func TestTypedReferenceIdentityAndAbsence(t *testing.T) {
	e := currentCardGame(t, 0)
	g := e.G
	g.CounterPerm = nil // identity layout must still emit reference entities
	kinds := e.RT.ObservationReferenceKinds()
	for _, kind := range []int{1, 2} {
		id := -1
		for candidate, k := range kinds {
			if k == kind {
				id = candidate
				break
			}
		}
		if id < 0 {
			t.Fatalf("no reference kind %d", kind)
		}
		g.Counters[id].Value = -1
		empty := g.BuildDynamicObs(0)
		raw, hook := -1, -1

		if kind == 1 {
			for k, h := range g.CanonicalSkillHooks {
				if k[0] == 1 {
					raw, hook = k[2], h
					break
				}
			}
		} else {
			for k, h := range g.CanonicalCardHooks {
				raw, hook = k, h
				break
			}
		}
		g.Counters[id].Value = raw
		before := g.BuildDynamicObs(0)
		if reflect.DeepEqual(empty, before) {
			t.Fatal("reference presence invisible")
		}
		rows := entityRows(g, 0, engine.EntitySkillReference+kind-1)
		found := false
		for _, r := range rows {
			if r[13] == int32(id) {
				found = true
				if r[3] != 1 || r[7] < 0 {
					t.Fatal(r)
				}
				if kind == 1 && r[14] != -1 {
					t.Fatal("shared skill must not invent actor", r)
				}
			}
		}
		if !found {
			t.Fatal("source binding missing")
		}
		// Renumber only the referenced identity and its canonical resolver. Numeric
		// storage must not leak the raw ID through counters or entity rows.
		g.Counters[id].Value = 900001
		if kind == 1 {
			for key, h := range g.CanonicalSkillHooks {
				if key[2] == raw {
					g.CanonicalSkillHooks[[3]int{key[0], key[1], 900001}] = h
				}
			}
		} else {
			g.CanonicalCardHooks[900001] = hook
		}
		if !reflect.DeepEqual(before, g.BuildDynamicObs(0)) {
			t.Fatal("raw identity leaked")
		}
		g.Counters[id].Value = -1
	}
}

func TestGenericPublicSlots(t *testing.T) {
	e := currentCardGame(t, 0)
	g := e.G
	refs := []int{}
	for ref := range g.CanonicalCardHooks {
		refs = append(refs, ref)
		if len(refs) == 2 {
			break
		}
	}
	g.Players[1].Supports = []engine.SupportInst{{Ref: refs[0], ActivatedAt: g.Round}}
	g.Players[0].Chars[0].SpecialtyCardRef = refs[1]
	support := entityRows(g, 0, engine.EntitySupport)
	talent := entityRows(g, 0, engine.EntitySpecialty)
	if len(support) != 1 || support[0][1] != 1 || support[0][4] != 0 {
		t.Fatal(support)
	}
	if len(talent) != 1 || talent[0][1] != 0 || talent[0][2] != 0 {
		t.Fatal(talent)
	}
	if entityRows(g, 1, engine.EntitySupport)[0][1] != 0 {
		t.Fatal("perspective")
	}
	g.Players[1].Supports[0].ActivatedAt--
	if reflect.DeepEqual(support, entityRows(g, 0, engine.EntitySupport)) {
		t.Fatal("support age invisible")
	}
	g.Players[1].Supports[0].Ref = refs[1]
	if support[0][7] == entityRows(g, 0, engine.EntitySupport)[0][7] {
		t.Fatal("support identity invisible")
	}
}

func TestReferenceRejectsMissingDefinition(t *testing.T) {
	e := currentCardGame(t, 0)
	for id := range e.RT.ObservationReferenceKinds() {
		e.G.Counters[id].Value = 999999
		defer func() {
			if recover() == nil {
				t.Fatal("unresolved reference silently accepted")
			}
		}()
		e.G.BuildDynamicObs(0)
		return
	}
	t.Fatal("missing fixture")
}

func TestUniqueSkillReferenceAndStaticBounds(t *testing.T) {
	e := currentCardGame(t, 0)
	g := e.G
	g.CounterPerm = nil
	for id, kind := range e.RT.ObservationReferenceKinds() {
		if kind != 1 {
			continue
		}
		for key, hook := range g.CanonicalSkillHooks {
			if key[0] != 1 {
				continue
			}
			g.CanonicalSkillHooks[[3]int{1, key[1], 999999}] = hook
			g.Counters[id].Value = 999999
			for _, row := range entityRows(g, 0, engine.EntitySkillReference) {
				if row[13] == int32(id) && (row[14] != 1 || row[15] != int32(key[1])) {
					t.Fatal(row)
				}
			}
			static := g.BuildStaticObs()
			g.Counters[id].Min = -1000
			g.Counters[id].Max = 999999
			if !reflect.DeepEqual(static, g.BuildStaticObs()) {
				t.Fatal("raw reference bounds leaked")
			}
			return
		}
	}
	t.Fatal("missing fixture")
}
