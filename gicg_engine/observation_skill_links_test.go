package engine

import (
	"math/rand"
	"reflect"
	"sort"
	"testing"
)

func TestSkillLinksBindMirrorActorsAndMultipleSkills(t *testing.T) {
	var expected [][2]int
	for seed := int64(7); seed < 12; seed++ {
		g := graphFixture(seed)
		g.CanonicalSkillHooks = map[[3]int]int{}
		canonical := func(p, skill int) int {
			h := g.Hooks.Register(Hook{Type: HookSkillUse, OwnerPlayer: p, OwnerChar: 0, Repr: CanonicalHookRepr{Marker: int16(skill)}})
			g.CanonicalSkillHooks[[3]int{p, 0, skill}] = h
			return h
		}
		a, b, c := canonical(0, 5), canonical(1, 5), canonical(0, 6)
		add := func(p int, refs []int) int {
			return g.Hooks.Register(Hook{Type: HookSkillUse, OwnerPlayer: p, OwnerChar: 0, SkillReferences: refs,
				Source: "same_file", Repr: CanonicalHookRepr{Marker: 9}})
		}
		x, y, z := add(0, []int{5}), add(1, []int{5}), add(0, []int{6})
		g.InitShuffle(rand.New(rand.NewSource(seed)))
		raw := map[int]int{}
		for r, active := range g.BuildRawToActiveHookIdx() {
			raw[active] = r
		}
		graph := g.BuildObservationRuleGraph()
		if graph.Version != 2 {
			t.Fatal("expected new graph version")
		}
		got := make([][2]int, 0)
		for _, row := range graph.SkillLinks {
			got = append(got, [2]int{raw[row[0]], raw[row[1]]})
		}
		sort.Slice(got, func(i, j int) bool { return got[i][0] < got[j][0] })
		want := [][2]int{{a, x}, {b, y}, {c, z}}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("wrong definition/owner links: %v want %v", got, want)
		}
		if expected != nil && !reflect.DeepEqual(expected, got) {
			t.Fatal("layout changed incidence")
		}
		expected = got
	}
}
