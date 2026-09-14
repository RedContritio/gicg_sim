package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func applyNativeElement(t *testing.T, env *GameEnv, player int, element string) {
	t.Helper()
	g := env.G
	g.PushEvent(engine.EventFrame{Player: player, Char: 0, Source: engine.SrcSummon})
	defer g.PopEvent()
	src := fmt.Sprintf("apply_element(Target.OwnActive, Element.%s)", element)
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatal(err)
	}
}

func TestPureAttachmentNeverEmitsDamage(t *testing.T) {
	for _, player := range []int{0, 1} {
		for _, aura := range []string{"雷元素附着", "火元素附着", "冰元素附着"} {
			t.Run(fmt.Sprintf("player%d_%s", player, aura), func(t *testing.T) {
				team := []string{"墨客", "猫咪", "赤蝶"}
				env := NewGame(t, team, team)
				setNativeAura(t, env, aura, player, 0)
				before := [2][3]int{}
				for p := 0; p < 2; p++ {
					for c := 0; c < 3; c++ {
						before[p][c] = env.HP(p, c)
					}
				}
				calls := 0
				for _, kind := range []engine.HookType{engine.HookDamageType, engine.HookDamageAdd, engine.HookDamageMul,
					engine.HookDamageReduceBuff, engine.HookShieldAbsorb, engine.HookDamageImmunity, engine.HookAfterDamage} {
					env.G.Hooks.Register(engine.Hook{Type: kind, Fn: func(_ *engine.Game, _ *engine.EventContext) { calls++ }})
				}
				applyNativeElement(t, env, player, "Water")
				if calls != 0 {
					t.Fatalf("pure attachment fired %d damage hooks", calls)
				}
				for p := 0; p < 2; p++ {
					for c := 0; c < 3; c++ {
						if env.HP(p, c) != before[p][c] {
							t.Fatalf("attachment damaged player %d character %d", p, c)
						}
					}
				}
				if aura == "冰元素附着" {
					id := -1
					for candidate, name := range env.G.CounterNames {
						if name == "冻结" && env.G.GetCounterChar(candidate) == [2]int{player, 0} {
							id = candidate
							break
						}
					}
					if id < 0 || env.G.Counters[id].Value != 1 {
						t.Fatal("non-damage freeze was lost")
					}
				}
			})
		}
	}
}

func TestShieldedDamageStillHasReactionCollateral(t *testing.T) {
	team := []string{"墨客", "猫咪", "赤蝶"}
	env := NewGame(t, team, team)
	setNativeAura(t, env, "水元素附着", 1, 0)
	before := [3]int{env.HP(1, 0), env.HP(1, 1), env.HP(1, 2)}
	mainEvents := 0
	env.G.Hooks.Register(engine.Hook{Type: engine.HookShieldAbsorb, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
		if ctx.TargetPlayer == 1 && ctx.TargetChar == 0 {
			if ctx.Value != 4 {
				t.Fatalf("reaction bonus missing before shield: %d", ctx.Value)
			}
			ctx.Value = 0
		}
	}})
	env.G.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
		if ctx.TargetPlayer == 1 && ctx.TargetChar == 0 {
			mainEvents++
			if ctx.Hit || ctx.Absorbed != 4 {
				t.Fatalf("wrong absorbed result: %+v", ctx)
			}
		}
	}})
	nativeDamage(env, 1, 0, engine.ElemElectro, 3)
	if env.HP(1, 0) != before[0] || env.HP(1, 1) != before[1]-1 || env.HP(1, 2) != before[2]-1 || mainEvents != 1 {
		t.Fatal("fully absorbed main hit lost collateral or after-damage event")
	}
}

func TestCrystallizeShieldCappedAndOnlyProtectsActive(t *testing.T) {
	team := []string{"墨客", "猫咪", "赤蝶"}
	env := NewGame(t, team, team)
	id := findCounterIDPerPlayer(env, "结晶护盾", 0)
	for i := 0; i < 4; i++ {
		setNativeAura(t, env, "水元素附着", 1, 0)
		nativeDamage(env, 1, 0, engine.ElemGeo, 1)
		want := i + 1
		if want > 2 {
			want = 2
		}
		if env.G.Counters[id].Value != want {
			t.Fatalf("crystal shield=%d want=%d", env.G.Counters[id].Value, want)
		}
	}
	before := env.HP(0, 1)
	nativeDamage(env, 0, 1, engine.ElemPhysical, 1)
	if env.HP(0, 1) != before-1 || env.G.Counters[id].Value != 2 {
		t.Fatal("crystal shield incorrectly protected background character")
	}
	nativeDamage(env, 0, 0, engine.ElemPhysical, 1)
	if env.G.Counters[id].Value != 1 {
		t.Fatal("active damage did not spend shield")
	}
	setNativeAura(t, env, "水元素附着", 1, 0)
	nativeDamage(env, 1, 0, engine.ElemGeo, 1)
	if env.G.Counters[id].Value != 2 {
		t.Fatal("crystal did not replenish to cap")
	}
}
