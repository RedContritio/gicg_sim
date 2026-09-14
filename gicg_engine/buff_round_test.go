package engine

import (
	"reflect"
	"testing"
)

func TestRoundBuffCrossPlayerOrder(t *testing.T) {
	for _, first := range []int{0, 1} {
		for _, summon := range []bool{false, true} {
			g := &Game{Hooks: NewHookRegistry(), FirstEnd: -1}
			var got []int
			// Registration order deliberately differs from creation order.
			ids := make([]int, 4)
			for i := range ids {
				id := g.CreateCounter(0, 0, 1)
				ids[i] = id
				g.RegisterCounterChar(id, i%2, i/2)
				g.EnableCounterOrder(id, false)
				g.BuffDefinitions[g.Counters[id].BuffIndex].Summon = summon
				i := i
				g.Hooks.Register(Hook{Type: HookRoundEnd, OwnerPlayer: FilterAny, OrderIDs: []int{id}, OrderCounter: func(*EventContext) int { return id }, Fn: func(g *Game, ctx *EventContext) {
					if ctx.ActorPlayer != i%2 || ctx.ActorChar != i/2 {
						t.Fatal("wrong buff owner")
					}
					got = append(got, i)
				}})
			}
			for _, i := range []int{3, 0, 1, 2} {
				g.WriteCounter(ids[i], OpSet, 1)
			}
			g.FirePerPlayerHooks(HookRoundEnd, &EventContext{}, []int{first, 1 - first})
			want := []int{3, 0, 1, 2}
			if summon {
				if first == 0 {
					want = []int{0, 2, 3, 1}
				} else {
					want = []int{3, 1, 0, 2}
				}
			}
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("first=%d summon=%v got=%v want=%v", first, summon, got, want)
			}
		}
	}
}

func TestRoundBuffAgendaDoesNotRunReplacement(t *testing.T) {
	g := &Game{Hooks: NewHookRegistry(), FirstEnd: -1}
	id := g.CreateCounter(0, 0, 1)
	g.RegisterCounterChar(id, 1, 0)
	g.EnableCounterOrder(id, false)
	g.WriteCounter(id, OpSet, 1)
	old := g.Buffs[0].ID
	g.Hooks.Register(Hook{Type: HookRoundEnd, OwnerPlayer: 0, Fn: func(g *Game, ctx *EventContext) {
		g.WriteCounter(id, OpSet, 0)
		g.WriteCounter(id, OpSet, 1)
	}})
	fired := 0
	g.Hooks.Register(Hook{Type: HookRoundEnd, OwnerPlayer: FilterAny, OrderIDs: []int{id}, OrderCounter: func(*EventContext) int { return id }, Fn: func(*Game, *EventContext) { fired++ }})
	g.FirePerPlayerHooks(HookRoundEnd, &EventContext{}, []int{1, 0})
	if fired != 0 || g.Buffs[0].ID == old {
		t.Fatal("replacement ran in stale agenda")
	}
}

func TestBuffObservationUsesInstanceStateAndPreciseHooks(t *testing.T) {
	g := &Game{Hooks: NewHookRegistry(), FirstEnd: -1}
	id := g.CreateCounter(0, 0, 9)
	g.RegisterCounterChar(id, 1, -1)
	g.EnableCounterOrder(id, false)
	d := &g.BuffDefinitions[0]
	d.Independent, d.Summon = true, true
	bound := g.Hooks.Register(Hook{Type: HookRoundEnd, Source: "same_file#0", Repr: CanonicalHookRepr{Marker: 1}})
	g.Hooks.Register(Hook{Type: HookRoundEnd, Source: "same_file#1", Repr: CanonicalHookRepr{Marker: 2}})
	d.HookIDs = []int{bound}
	d.RuleSources = []string{"same_file"}
	for _, state := range [][2]int{{2, 1}, {3, 2}} {
		if _, err := g.SpawnBuff(0, state[0], state[1]); err != nil {
			t.Fatal(err)
		}
	}
	out := make([]int32, ObsBuffSlots)
	g.writeBuffObs(out, 0)
	for i, state := range [][2]int{{2, 1}, {3, 2}} {
		row := out[i*ObsBuffFields : (i+1)*ObsBuffFields]
		if row[0] != 1 || row[1] != 1 || row[3] != int32(state[0]) || row[4] != int32(state[1]) || row[6] != int32(i) || row[11] != 1 {
			t.Fatalf("wrong row %v", row)
		}
	}
	if out[2*ObsBuffFields] != 0 {
		t.Fatal("unrelated file hook leaked into buff program")
	}
	for _, first := range []int{0, 1} {
		g.FirstEnd = first
		for _, perspective := range []int{0, 1} {
			visible := make([]int32, ObsBuffSlots)
			g.writeBuffObs(visible, perspective)
			want := int32(3)
			if first == 1 {
				want = 2
			}
			if visible[11] != want {
				t.Fatal("ending-player order invisible")
			}
		}
	}
	g.FirstEnd = -1
	for i := range g.Buffs {
		g.Buffs[i].ID += 100
	}
	after := make([]int32, ObsBuffSlots)
	g.writeBuffObs(after, 0)
	if !reflect.DeepEqual(out, after) {
		t.Fatal("lifecycle serial leaked to NN")
	}
}
