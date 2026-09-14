package tests

import (
	engine "gicg_mono/gicg_engine"
	"math/rand"
	"reflect"
	"testing"
)

type layerModel struct{ Owner, Value, Duration int }

func TestRandomIndependentLayersAgainstReference(t *testing.T) {
	for seed := int64(0); seed < 24; seed++ {
		t.Logf("independent layer seed=%d", seed)
		e := currentCardGame(t, 0)
		_, err := execDSL(e, `
 local b = declare_counter("random_layers", Scope.PerPlayer, 0, {min=0,max=9})
 register_buff(b,{independent=true})
 on_damage_reduce_buff({order=b},function(ctx)
   local used=min(ctx.value,b:get())
   ctx.value=ctx.value-used
   b:sub(used)
 end)
 on_round_end_decay({order=b},function(ctx)
   if buff_duration()>0 then set_buff_duration(buff_duration()-1) end
 end)
 `)
		if err != nil {
			t.Fatal(err)
		}
		rng := rand.New(rand.NewSource(seed))
		model := []layerModel{}
		ids := [2]int{findCounterIDPerPlayer(e, "random_layers", 0), findCounterIDPerPlayer(e, "random_layers", 1)}
		for step := 0; step < 160; step++ {
			p := rng.Intn(2)
			switch rng.Intn(4) {
			case 0:
				value, duration := 1+rng.Intn(5), 1+rng.Intn(4)
				if _, err := e.G.SpawnBuff(e.G.Counters[ids[p]].BuffIndex, value, duration); err != nil {
					t.Fatal(err)
				}
				model = append(model, layerModel{p, value, duration})
			case 1:
				damage := 1 + rng.Intn(8)
				expected := damage
				for i := range model {
					if model[i].Owner == p {
						used := min(expected, model[i].Value)
						model[i].Value -= used
						expected -= used
					}
				}
				ctx := &engine.EventContext{Value: damage, ActorPlayer: 1 - p, ActorChar: 0, TargetPlayer: p, TargetChar: 0}
				e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0}, func(g *engine.Game) { g.FireEventHooks(engine.HookDamageReduceBuff, ctx) })
				if ctx.Value != expected {
					t.Fatalf("seed=%d step=%d wrong remaining damage", seed, step)
				}
			case 2:
				e.G.FirePerPlayerHooks(engine.HookRoundEndDecay, &engine.EventContext{}, []int{p, 1 - p})
				for i := range model {
					model[i].Duration--
				}
			case 3:
				e.G.WriteCounter(ids[p], engine.OpSet, 0)
				for i := range model {
					if model[i].Owner == p {
						model[i].Value = 0
					}
				}
			}
			live := model[:0]
			for _, b := range model {
				if b.Value > 0 && b.Duration > 0 {
					live = append(live, b)
				}
			}
			model = live
			actual := []layerModel{}
			for _, b := range e.G.Buffs {
				actual = append(actual, layerModel{e.G.GetCounterChar(e.G.BuffDefinitions[b.Definition].CounterID)[0], b.Value, b.Duration})
			}
			if !reflect.DeepEqual(model, actual) {
				t.Fatalf("seed=%d step=%d got=%v want=%v", seed, step, actual, model)
			}
			if step%11 == 0 {
				state := sequenceState(t, e.G)
				snap := e.G.SnapshotPooled()
				e.G.WriteCounter(ids[p], engine.OpSet, 0)
				e.G.RestoreFromSnap(snap)
				engine.ReleaseSnap(snap)
				if !reflect.DeepEqual(state, sequenceState(t, e.G)) {
					t.Fatalf("seed=%d step=%d restore mismatch", seed, step)
				}
			}
		}
	}
}
