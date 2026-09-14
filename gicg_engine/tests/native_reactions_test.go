package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func setNativeAura(t *testing.T, env *GameEnv, name string, player, char int) {
	t.Helper()
	src := fmt.Sprintf(`get_counter("%s", Scope.PerChar):set_at(%d, %d, 1)`, name, player, char)
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatal(err)
	}
}

func nativeDamage(env *GameEnv, player, char int, elem engine.Element, amount int) {
	g := env.G
	g.PushEvent(engine.EventFrame{Player: 1 - player, Char: 0, Source: engine.SrcSkill})
	defer g.PopEvent()
	g.DealDamage(env.RT.Chars.BySlot[player][char].HPCounterID, elem, amount,
		engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
}

func TestNativeFrozenBonusAndPhysicalShatter(t *testing.T) {
	for _, player := range []int{0, 1} {
		for _, elem := range []engine.Element{engine.ElemPhysical, engine.ElemFire} {
			t.Run(fmt.Sprintf("player%d_element%d", player, elem), func(t *testing.T) {
				env := NewGame(t, []string{"墨客", "猫咪"}, []string{"墨客", "猫咪"})
				setNativeAura(t, env, "水元素附着", player, 0)
				before := env.HP(player, 0)
				nativeDamage(env, player, 0, engine.ElemIce, 1)
				if got := before - env.HP(player, 0); got != 2 {
					t.Fatalf("freeze must add 1 to damage: %d", got)
				}
				before = env.HP(player, 0)
				nativeDamage(env, player, 0, elem, 1)
				if got := before - env.HP(player, 0); got != 3 {
					t.Fatalf("shatter must add 2: %d", got)
				}
				before = env.HP(player, 0)
				nativeDamage(env, player, 0, engine.ElemPhysical, 1)
				if got := before - env.HP(player, 0); got != 1 {
					t.Fatalf("freeze must be consumed: %d", got)
				}
			})
		}
	}
}

func TestNativeConductBonusIsOneShieldableHit(t *testing.T) {
	for _, aura := range []string{"冰元素附着", "水元素附着"} {
		for _, player := range []int{0, 1} {
			for _, target := range []int{0, 1} {
				t.Run(fmt.Sprintf("%s_player%d_target%d", aura, player, target), func(t *testing.T) {
					team := []string{"墨客", "猫咪", "赤蝶"}
					env := NewGame(t, team, team)
					setNativeAura(t, env, aura, player, target)
					before := [3]int{env.HP(player, 0), env.HP(player, 1), env.HP(player, 2)}
					mainHits := 0
					env.G.Hooks.Register(engine.Hook{Type: engine.HookDamageReduceBuff, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
						if ctx.TargetPlayer == player && ctx.TargetChar == target {
							if ctx.Value != 4 {
								t.Fatalf("main hit must include reaction before mitigation: %d", ctx.Value)
							}
							ctx.Value -= 3
						}
					}})
					env.G.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
						if ctx.TargetPlayer == player && ctx.TargetChar == target {
							mainHits++
						}
					}})
					nativeDamage(env, player, target, engine.ElemElectro, 3)
					for c := 0; c < 3; c++ {
						if got := before[c] - env.HP(player, c); got != 1 {
							t.Fatalf("character %d lost %d, expected 1", c, got)
						}
					}
					if mainHits != 1 {
						t.Fatalf("main target must have one damage event: %d", mainHits)
					}
				})
			}
		}
	}
}
