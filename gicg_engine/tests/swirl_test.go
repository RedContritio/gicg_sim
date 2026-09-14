package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestSwirlPreservesAnemoAndSpreadsOriginalAura(t *testing.T) {
	for _, player := range []int{0, 1} {
		for _, spec := range []struct {
			aura    string
			element engine.Element
		}{
			{"火元素附着", engine.ElemFire}, {"水元素附着", engine.ElemWater},
			{"冰元素附着", engine.ElemIce}, {"雷元素附着", engine.ElemElectro},
		} {
			t.Run(fmt.Sprintf("%d_%s", player, spec.aura), func(t *testing.T) {
				team := []string{"赤蝶", "墨客", "猫咪"}
				env := NewGame(t, team, team)
				setNativeAura(t, env, spec.aura, player, 0)
				before := [3]int{env.HP(player, 0), env.HP(player, 1), env.HP(player, 2)}
				resolved := false
				env.G.Hooks.Register(engine.Hook{Type: engine.HookAfterReaction, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
					if ctx.ReactionKind != env.G.ReactionRegistry["Swirl"] {
						return
					}
					if ctx.ReactionElement != spec.element || ctx.TargetPlayer != player {
						t.Fatalf("wrong reaction metadata: %+v", ctx)
					}
					resolved = true
				}})
				hits := 0
				env.G.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
					if ctx.TargetPlayer != player {
						return
					}
					hits++
					if ctx.TargetChar == 0 && ctx.Element != engine.ElemAnemo {
						t.Fatalf("reaction erased main damage element: %v", ctx.Element)
					}
					if ctx.TargetChar != 0 && (ctx.Element != spec.element || !resolved || ctx.Source != engine.SrcReaction) {
						t.Fatalf("wrong collateral: %+v", ctx)
					}
				}})
				nativeDamage(env, player, 0, engine.ElemAnemo, 3)
				if !resolved || hits != 3 || env.HP(player, 0) != before[0]-3 || env.HP(player, 1) != before[1]-1 || env.HP(player, 2) != before[2]-1 {
					t.Fatal("wrong swirl damage")
				}
			})
		}
	}
}

func TestSwirlCollateralCanReactAndPureApplicationDoesNotDamage(t *testing.T) {
	for _, pure := range []bool{false, true} {
		t.Run(fmt.Sprint(pure), func(t *testing.T) {
			team := []string{"赤蝶", "墨客", "猫咪"}
			env := NewGame(t, team, team)
			setNativeAura(t, env, "火元素附着", 1, 0)
			setNativeAura(t, env, "水元素附着", 1, 1)
			before := [3]int{env.HP(1, 0), env.HP(1, 1), env.HP(1, 2)}
			if pure {
				applyNativeElement(t, env, 1, "Anemo")
			} else {
				nativeDamage(env, 1, 0, engine.ElemAnemo, 1)
			}
			want := [3]int{1, 3, 1}
			if pure {
				want = [3]int{0, 0, 0}
			}
			for c := 0; c < 3; c++ {
				if before[c]-env.HP(1, c) != want[c] {
					t.Fatalf("char %d lost %d want %d", c, before[c]-env.HP(1, c), want[c])
				}
			}
		})
	}
}
