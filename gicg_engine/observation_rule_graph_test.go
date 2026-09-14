package engine

import (
	"encoding/json"
	"math/rand"
	"reflect"
	"sort"
	"strings"
	"testing"
)

func graphFixture(seed int64) *Game {
	g := &Game{Hooks: NewHookRegistry(), Counters: []Counter{{Min: 0, Max: 10}, {Min: 0, Max: 10}},
		Obs: NewDefaultObsConfig(), CanonicalCardHooks: map[int]int{}}
	h := g.Hooks.Register(Hook{Type: HookCardPlay, Source: "private_card_name#0",
		Repr: CanonicalHookRepr{Marker: 1}, CounterAccess: []HookCounterAccess{
			{Symbol: "private_counter_name", Method: "get", CounterIDs: []int{0}},
			{Symbol: "second", Method: "set", CounterIDs: []int{1}},
		}})
	g.CanonicalCardHooks[1] = h
	g.Hooks.Register(Hook{Type: HookCardPlay, Source: "private_card_name#1", Repr: CanonicalHookRepr{Marker: 2}})
	g.InitShuffle(rand.New(rand.NewSource(seed)))
	return g
}

func normalizeGraph(g *Game) ([][4]int, [][2]int) {
	x := g.BuildObservationRuleGraph()
	s := g.BuildStaticObs()
	activeToRaw := map[int]int{}
	for raw, active := range g.BuildRawToActiveHookIdx() {
		activeToRaw[active] = raw
	}
	for i, row := range x.CounterLinks {
		x.CounterLinks[i][0] = g.CounterPerm[int(s[row[0]*3+2])]
		x.CounterLinks[i][1] = activeToRaw[row[1]]
	}
	for i, row := range x.CardLinks {
		x.CardLinks[i][0] = g.CardPerm[row[0]] + 1
		x.CardLinks[i][1] = activeToRaw[row[1]]
	}
	sort.Slice(x.CounterLinks, func(i, j int) bool { return x.CounterLinks[i][0] < x.CounterLinks[j][0] })
	sort.Slice(x.CardLinks, func(i, j int) bool { return x.CardLinks[i][1] < x.CardLinks[j][1] })
	return x.CounterLinks, x.CardLinks
}

func TestRuleGraphPreservesReferencesAcrossLayouts(t *testing.T) {
	a, b := normalizeGraph(graphFixture(7))
	if len(a) != 2 || len(b) != 2 {
		t.Fatalf("missing rule links: %v %v", a, b)
	}
	for seed := int64(8); seed < 28; seed++ {
		c, d := normalizeGraph(graphFixture(seed))
		if !reflect.DeepEqual(a, c) || !reflect.DeepEqual(b, d) {
			t.Fatalf("shuffle changed physical references at seed %d", seed)
		}
	}
}

func TestRuleGraphContainsSchemaNotValuesOrNames(t *testing.T) {
	g := graphFixture(7)
	a := g.BuildObservationRuleGraph()
	g.Counters[0].Value = 9
	b := g.BuildObservationRuleGraph()
	if !reflect.DeepEqual(a, b) {
		t.Fatal("dynamic values changed static reference graph")
	}
	if len(a.CardHookLinks) != 1 || a.CardHookLinks[0][0] == a.CardHookLinks[0][1] {
		t.Fatal("card canonical hook must reference its separate effect")
	}
	data, err := json.Marshal(a)
	if err != nil || strings.Contains(string(data), "private_") {
		t.Fatal("graph leaked binding names")
	}
}

func TestStaticObservationCarriesDefinitionLinksInShuffledLayout(t *testing.T) {
	for seed := int64(7); seed < 20; seed++ {
		g := graphFixture(seed)
		graph := g.BuildObservationRuleGraph()
		want := append(append(make([][2]int, 0), graph.SkillLinks...), graph.CardHookLinks...)
		sort.Slice(want, func(i, j int) bool {
			return want[i][0] < want[j][0] || (want[i][0] == want[j][0] && want[i][1] < want[j][1])
		})

		obs := g.BuildStaticObs()
		offset := obsCounterSlots()*3 + 2*ObsMaxChars*ObsMaxSkillsPerChar +
			ObsMaxHooks*ObsIntsPerHook + ObsCharElementSlots
		if obs[offset] != ObsDefinitionLinkSchemaVersion {
			t.Fatalf("seed %d definition schema %d", seed, obs[offset])
		}
		count := int(obs[offset+1])
		got := make([][2]int, count)
		for i := range count {
			got[i] = [2]int{int(obs[offset+2+2*i]), int(obs[offset+3+2*i])}
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("seed %d static definition links %v, want %v", seed, got, want)
		}
	}
}
