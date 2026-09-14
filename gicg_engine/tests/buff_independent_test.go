package tests

import (
	engine "gicg_mono/gicg_engine"
	"reflect"
	"testing"
)

func TestIndependentBuffChargesDurationAndRestore(t *testing.T) {
	e := currentCardGame(t, 0)
	_, err := execDSL(e, `
 local b = declare_counter("independent_probe", Scope.PerPlayer, 0, { min=0, max=9 })
 register_buff(b, { independent=true })
 on_damage_reduce_buff({order=b}, function(ctx)
   local used = min(ctx.value, b:get())
   ctx.value = ctx.value - used
   b:sub(used)
 end)
 on_round_end_decay({order=b}, function(ctx)
   set_buff_duration(buff_duration() - 1)
 end)
 spawn_buff(b, 2, 1, 0, 0)
 spawn_buff(b, 3, 2, 0, 0)
 `)
	if err != nil {
		t.Fatal(err)
	}
	id := findCounterIDPerPlayer(e, "independent_probe", 0)
	if e.G.ReadCounter(id) != 5 {
		t.Fatal("independent instances did not spawn")
	}
	before := append([]engine.BuffInstance(nil), e.G.Buffs...)
	snap := e.G.SnapshotPooled()
	defer engine.ReleaseSnap(snap)
	for attempt := 0; attempt < 2; attempt++ {
		ctx := &engine.EventContext{Value: 1, TargetPlayer: 0, TargetChar: 0}
		e.G.ExecuteEffect(engine.EventFrame{Player: 1, Char: 0}, func(g *engine.Game) {
			g.FireEventHooks(engine.HookDamageReduceBuff, ctx)
		})
		if ctx.Value != 0 || e.G.Buffs[0].Value != 1 || e.G.Buffs[1].Value != 3 {
			t.Fatal("charges shared or second instance consumed")
		}
		e.G.FirePerPlayerHooks(engine.HookRoundEndDecay, &engine.EventContext{}, []int{1, 0})
		if len(e.G.Buffs) != 1 || e.G.Buffs[0].Duration != 1 || e.G.Buffs[0].Value != 3 {
			t.Fatal("expiry not independent")
		}
		e.G.RestoreFromSnap(snap)
		if !reflect.DeepEqual(e.G.Buffs, before) {
			t.Fatal("restore lost independent state")
		}
	}
	e.G.WriteCounter(id, engine.OpSet, 0)
	if len(e.G.Buffs) != 0 {
		t.Fatal("template clear did not remove all instances")
	}
}

func TestIndependentBuffApplicationConsumption(t *testing.T) {
	e := currentCardGame(t, 0)
	_, err := execDSL(e, `
 local b = declare_counter("independent_cost", Scope.PerPlayer, 0, { min=0, max=3 })
 register_buff(b, {independent=true})
 local prep = on_action_prepare({order=b}, function(ctx)
   if ctx.action_kind ~= ActionKind.Skill then return end
   cost_reduce(ctx, 3)
 end)
 on_skill_use({order=b}, function(ctx)
   if was_applied(ctx, prep) then b:sub(1) end
 end)
 spawn_buff(b, 1, 1, 0, 0)
 spawn_buff(b, 1, 2, 0, 0)
 `)
	if err != nil {
		t.Fatal(err)
	}
	auditSkill(t, e, 0, "枪")
	if len(e.G.Buffs) != 1 || e.G.Buffs[0].Duration != 2 {
		t.Fatalf("unused instance consumed: %+v", e.G.Buffs)
	}
}

func TestIndependentBuffTagWriteKeepsWrittenInstance(t *testing.T) {
	e := currentCardGame(t, 0)
	_, err := execDSL(e, `
 local b = declare_counter("layer_shield", Scope.PerPlayer, 0, {min=0,max=9,tag=Tag.Shield})
 local active = declare_counter("layer_cap", Scope.PerPlayer, 0, {min=0,max=1})
 register_buff(b, {independent=true})
 register_buff(active)
 register_on_tag_write(Tag.Shield, "after", Op.Add, {order=active}, function(ctx, written)
   if written:get() > 1 then written:set(1) end
 end)
 active:set_at(0,1)
 spawn_buff(b,3,1,0,0)
 spawn_buff(b,4,2,0,0)
 `)
	if err != nil {
		t.Fatal(err)
	}
	id := findCounterIDPerPlayer(e, "layer_shield", 0)
	if e.G.ReadCounter(id) != 2 {
		t.Fatal("write hook lost the written instance")
	}
	for _, b := range e.G.Buffs {
		if b.Independent && b.Value != 1 {
			t.Fatal("write applied to wrong layer")
		}
	}
}
