package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"testing"
)

func nativeTalentGame(t *testing.T, name string) *GameEnv {
	team := []string{name}
	for _, other := range []string{"凯亚", "砂糖", "芭芭拉"} {
		if other != name && len(team) < 3 {
			team = append(team, other)
		}
	}
	e := newGame(t, team, team, 42, false, "native_latest")
	for p := 0; p < 2; p++ {
		e.SetDice(p, map[int]int{engine.DiceColorOmni: 16})
		e.G.WriteCounter(e.RT.Chars.BySlot[p][0].HPCounterID, engine.OpSet, 6)
		energy := 0
		if name == "砂糖" {
			energy = 2
		}
		e.G.WriteCounter(e.RT.Chars.BySlot[p][0].EnergyCounterID, engine.OpSet, energy)
	}
	return e
}

func TestNativeTalentsPayOnceAndInvokeSkillOnBothSeats(t *testing.T) {
	for _, spec := range []struct {
		name, card string
		damage     int
	}{
		{"凯亚", "冷血之剑", 3}, {"迪卢克", "流火焦灼", 3}, {"芭芭拉", "光辉的季节", 1},
		{"砂糖", "混元熵增论", 1}, {"菲谢尔", "噬星魔鸦", 1},
	} {
		for _, p := range []int{0, 1} {
			t.Run(fmt.Sprintf("%s_P%d", spec.name, p), func(t *testing.T) {
				e := nativeTalentGame(t, spec.name)
				source := engine.SrcNone
				e.G.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
					if ctx.ActorPlayer == p {
						source = ctx.Source
					}
				}})
				auditPlay(t, e, p, spec.card)
				if e.DiceTotal(p) != 13 || e.HP(1-p, 0) != 6-spec.damage || source != engine.SrcSkill {
					t.Fatalf("wrong payment/damage/source: dice=%d hp=%d source=%v", e.DiceTotal(p), e.HP(1-p, 0), source)
				}
				energy := 1
				if spec.name == "砂糖" {
					energy = 0
				}
				if e.Energy(p, 0) != energy {
					t.Fatalf("energy=%d want=%d", e.Energy(p, 0), energy)
				}
				if e.G.Turn != 1-p {
					t.Fatal("talent must be battle action")
				}
				if spec.name == "凯亚" && e.HP(p, 0) != 8 {
					t.Fatal("cold-blooded strike did not heal on equipment skill")
				}
			})
		}
	}
}

func TestNativeDilucTalentDiscountsOnlySecondAndThird(t *testing.T) {
	e := nativeTalentGame(t, "迪卢克")
	auditPlay(t, e, 0, "流火焦灼")
	for _, want := range []int{2, 2, 3} {
		e.G.WriteCounter(e.RT.Chars.BySlot[1][0].HPCounterID, engine.OpSet, 10)
		before := e.DiceTotal(0)
		auditSkill(t, e, 0, "逆焰之刃")
		if before-e.DiceTotal(0) != want {
			t.Fatalf("discounted cost=%d want=%d", before-e.DiceTotal(0), want)
		}
	}
}

func TestNativeBarbaraTalentSwitchCharge(t *testing.T) {
	e := nativeTalentGame(t, "芭芭拉")
	auditPlay(t, e, 0, "光辉的季节")
	e.G.ForceSwitchTo(0, 1)
	before := e.DiceTotal(0)
	auditSwitch(t, e, 0, 0)
	if e.DiceTotal(0) != before {
		t.Fatal("forced switch consumed discount or first voluntary switch was not free")
	}
	auditSwitch(t, e, 0, 1)
	if e.DiceTotal(0) != before-1 {
		t.Fatal("discount used twice in one round")
	}
}

func TestNativeFischlTalentOzConsumesExtraAttack(t *testing.T) {
	e := nativeTalentGame(t, "菲谢尔")
	auditPlay(t, e, 0, "噬星魔鸦")
	e.G.WriteCounter(e.RT.Chars.BySlot[1][0].HPCounterID, engine.OpSet, 10)
	auditSkill(t, e, 0, "罪灭之矢")
	if e.HP(1, 0) != 6 || e.G.Counters[findCounterIDPerPlayer(e, "奥兹", 0)].Value != 1 {
		t.Fatal("Oz talent attack or usage wrong")
	}
}

func TestNativeSucroseTalentBoostsConvertedSummon(t *testing.T) {
	e := nativeTalentGame(t, "砂糖")
	auditPlay(t, e, 0, "混元熵增论")
	e.G.WriteCounter(e.RT.Chars.BySlot[1][0].HPCounterID, engine.OpSet, 10)
	setNativeAura(t, e, "水元素附着", 1, 0)
	auditSkill(t, e, 0, "简式风灵作成")
	before := e.HP(1, 0)
	e.G.FirePerPlayerHooks(engine.HookRoundEndPostSummon, &engine.EventContext{}, []int{0, 1})
	if e.HP(1, 0) != before-3 {
		t.Fatal("converted talent wind spirit did not deal 3 water damage")
	}
}

func TestNativeKaeyaTalentHealsOncePerRound(t *testing.T) {
	e := nativeTalentGame(t, "凯亚")
	auditPlay(t, e, 0, "冷血之剑")
	e.G.WriteCounter(e.RT.Chars.BySlot[1][0].HPCounterID, engine.OpSet, 10)
	auditSkill(t, e, 0, "霜袭")
	if e.HP(0, 0) != 8 {
		t.Fatal("healed more than once in round")
	}
	e.G.FirePerPlayerHooks(engine.HookRoundStart, &engine.EventContext{}, []int{0, 1})
	e.SetDice(0, map[int]int{engine.DiceColorOmni: 16})
	auditSkill(t, e, 0, "霜袭")
	if e.HP(0, 0) != 10 {
		t.Fatal("healing use did not reset")
	}
}

func TestNativePiercingCannotReceiveSkillDamageBoost(t *testing.T) {
	e := nativeSkillGame(t, "菲谢尔")
	e.G.Hooks.Register(engine.Hook{Type: engine.HookDamageAdd, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
		if ctx.ActorPlayer == 0 {
			ctx.Value++
		}
	}})
	auditSkill(t, e, 0, "至夜幻现")
	if e.HP(1, 0) != 5 || e.HP(1, 1) != 8 || e.HP(1, 2) != 8 {
		t.Fatal("skill boost modified piercing damage")
	}
}
