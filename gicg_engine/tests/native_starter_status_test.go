package tests

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

func starterStatusGame(t *testing.T, first string) *GameEnv {
	team := []string{first, "凯亚"}
	if first == "凯亚" {
		team = []string{"凯亚", "砂糖"}
	}
	e := newGame(t, team, team, 42, false, "native_latest")
	for p := 0; p < 2; p++ {
		e.SetDice(p, map[int]int{engine.DiceColorOmni: 16})
		id := e.RT.Chars.BySlot[p][0].EnergyCounterID
		e.G.WriteCounter(id, engine.OpSet, e.G.Counters[id].Max)
	}
	return e
}

func TestNativeWindSpiritConvertsOnceAndOutlivesOwner(t *testing.T) {
	e := starterStatusGame(t, "砂糖")
	auditSkill(t, e, 0, "禁·风灵作成·柒伍同构贰型")
	uses := findCounterIDPerPlayer(e, "大型风灵", 0)
	element := findCounterIDPerPlayer(e, "大型风灵_元素", 0)
	if e.G.Counters[uses].Value != 3 || e.G.Counters[element].Value != int(engine.ElemAnemo) {
		t.Fatal("missing fresh wind spirit")
	}
	setNativeAura(t, e, "水元素附着", 1, 0)
	auditSkill(t, e, 0, "简式风灵作成")
	if e.G.Counters[element].Value != int(engine.ElemWater) {
		t.Fatal("wind spirit did not convert to water")
	}
	setNativeAura(t, e, "火元素附着", 1, 0)
	auditSkill(t, e, 0, "简式风灵作成")
	if e.G.Counters[element].Value != int(engine.ElemWater) {
		t.Fatal("wind spirit converted twice")
	}
	// Defeat the creator; the team-owned summon remains.
	e.G.SetAlive(0, 0, false)
	e.G.ForceSwitchTo(0, 1)
	before := e.HP(1, 0)
	e.G.FirePerPlayerHooks(engine.HookRoundEndPostSummon, &engine.EventContext{}, []int{0, 1})
	if e.HP(1, 0) != before-2 || e.G.Counters[uses].Value != 2 {
		t.Fatal("summon did not survive creator or consume one use")
	}
}

func TestNativeIcicleTriggersActualSwitchOnBothSides(t *testing.T) {
	for _, p := range []int{0, 1} {
		e := starterStatusGame(t, "凯亚")
		auditSkill(t, e, p, "凛冽轮舞")
		id := findCounterIDPerPlayer(e, "寒冰之棱", p)
		before := e.HP(1-p, 0)
		e.G.ForceSwitchTo(p, 1)
		if e.HP(1-p, 0) != before-2 || e.G.Counters[id].Value != 2 {
			t.Fatal("forced switch did not trigger icicle exactly once")
		}
		e.G.ForceSwitchTo(p, 1)
		if e.G.Counters[id].Value != 2 {
			t.Fatal("unchanged active consumed icicle")
		}
		auditSwitch(t, e, p, 0)
		if e.G.Counters[id].Value != 1 {
			t.Fatal("voluntary switch did not trigger icicle")
		}
	}
}
