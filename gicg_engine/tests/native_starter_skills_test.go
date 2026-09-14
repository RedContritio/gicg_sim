package tests

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

func nativeSkillGame(t *testing.T, name string) *GameEnv {
	e := newGame(t, []string{name, "凯亚", "砂糖"}, []string{"凯亚", "砂糖", "菲谢尔"}, 42, false, "native_latest")
	e.SetDice(0, map[int]int{engine.DiceColorOmni: 16})
	e.G.WriteCounter(e.RT.Chars.BySlot[0][0].EnergyCounterID, engine.OpSet, 3)
	return e
}

func TestNativeDilucThirdSkillOnlyAndInfusion(t *testing.T) {
	e := nativeSkillGame(t, "迪卢克")
	hp := e.RT.Chars.BySlot[1][0].HPCounterID
	for _, want := range []int{3, 3, 5, 3} {
		e.G.WriteCounter(hp, engine.OpSet, 10)
		e.SetDice(0, map[int]int{engine.DiceColorOmni: 16})
		auditSkill(t, e, 0, "逆焰之刃")
		if e.HP(1, 0) != 10-want {
			t.Fatalf("skill damage=%d want=%d", 10-e.HP(1, 0), want)
		}
	}
	e.G.WriteCounter(hp, engine.OpSet, 10)
	e.SetDice(0, map[int]int{engine.DiceColorOmni: 16})
	auditSkill(t, e, 0, "黎明")
	if e.HP(1, 0) != 2 {
		t.Fatal("burst must deal 8")
	}
	e.G.WriteCounter(hp, engine.OpSet, 10)
	element := engine.ElemNone
	e.G.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
		if ctx.ActorPlayer == 0 {
			element = ctx.Element
		}
	}})
	auditSkill(t, e, 0, "淬炼之剑")
	if element != engine.ElemFire {
		t.Fatal("physical normal attack was not infused")
	}
	for i := 0; i < 2; i++ {
		e.G.FirePerPlayerHooks(engine.HookRoundEndDecay, &engine.EventContext{}, []int{0, 1})
	}
	auditSkill(t, e, 0, "淬炼之剑")
	if element != engine.ElemPhysical {
		t.Fatal("infusion outlived two rounds")
	}
}

func TestNativeBarbaraRingHealsAllAndAppliesWithoutDamage(t *testing.T) {
	e := nativeSkillGame(t, "芭芭拉")
	for c := 0; c < 3; c++ {
		e.G.WriteCounter(e.RT.Chars.BySlot[0][c].HPCounterID, engine.OpSet, 6)
	}
	auditSkill(t, e, 0, "演唱，开始♪")
	setNativeAura(t, e, "雷元素附着", 0, 0)
	calls := 0
	e.G.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Fn: func(_ *engine.Game, _ *engine.EventContext) { calls++ }})
	e.G.FirePerPlayerHooks(engine.HookRoundEndPostSummon, &engine.EventContext{}, []int{0, 1})
	for c := 0; c < 3; c++ {
		if e.HP(0, c) != 7 {
			t.Fatalf("ring HP[%d]=%d", c, e.HP(0, c))
		}
	}
	if calls != 0 {
		t.Fatal("water ring attachment generated damage")
	}
	id := findCounterIDPerPlayer(e, "歌声之环", 0)
	if e.G.Counters[id].Value != 1 {
		t.Fatal("ring did not consume one usage")
	}
	auditSkill(t, e, 0, "闪耀奇迹")
	for c := 0; c < 3; c++ {
		if e.HP(0, c) != 10 {
			t.Fatal("burst did not heal team")
		}
	}
}

func TestNativeFischlBurstAndOz(t *testing.T) {
	e := nativeSkillGame(t, "菲谢尔")
	auditSkill(t, e, 0, "至夜幻现")
	if e.HP(1, 0) != 6 || e.HP(1, 1) != 8 || e.HP(1, 2) != 8 {
		t.Fatal("burst active/background damage mismatch")
	}
	auditSkill(t, e, 0, "夜巡影翼")
	id := findCounterIDPerPlayer(e, "奥兹", 0)
	before := e.HP(1, 0)
	e.G.FirePerPlayerHooks(engine.HookRoundEndPostSummon, &engine.EventContext{}, []int{0, 1})
	if e.HP(1, 0) != before-1 || e.G.Counters[id].Value != 1 {
		t.Fatal("Oz damage/usage mismatch")
	}
}
