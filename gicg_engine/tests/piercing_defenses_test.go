package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestPiercingBypassesModifiersAndPreservesDefenses(t *testing.T) {
	for _, player := range []int{0, 1} {
		for _, target := range []int{0, 1} {
			t.Run(fmt.Sprintf("player%d_target%d", player, target), func(t *testing.T) {
				team := []string{"凯亚", "迪卢克", "芭芭拉"}
				env := newGame(t, team, team, 42, false, "native_latest")
				g := env.G
				shield := findCounterIDPerPlayer(env, "结晶护盾", player)
				g.WriteCounter(shield, engine.OpSet, 2)
				stages := []engine.HookType{engine.HookDamageType, engine.HookDamageAdd,
					engine.HookDamageMul, engine.HookReactionDamage, engine.HookDamageReduceBuff,
					engine.HookShieldAbsorb, engine.HookDamageImmunity}
				uses := make([]int, len(stages))
				for i, kind := range stages {
					uses[i] = g.CreateCounter(1, 0, 1)
					g.Hooks.Register(engine.Hook{Type: kind, Fn: func(g *engine.Game, ctx *engine.EventContext) {
						g.WriteCounter(uses[i], engine.OpSub, 1)
						switch kind {
						case engine.HookDamageAdd:
							ctx.Value += 2
						case engine.HookDamageMul:
							ctx.Value *= 2
						case engine.HookDamageReduceBuff, engine.HookShieldAbsorb:
							ctx.Value--
						case engine.HookDamageImmunity:
							ctx.Value = 0
						}
					}})
				}
				after := 0
				g.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
					if ctx.Element != engine.ElemPiercing {
						return
					}
					after++
					if ctx.Value != 2 || ctx.Absorbed != 0 || !ctx.Hit || ctx.ReactionKind != engine.ReactionNone {
						t.Fatalf("incorrect piercing damage event: %+v", ctx)
					}
				}})
				before := env.HP(player, target)
				nativeDamage(env, player, target, engine.ElemPiercing, 2)
				if env.HP(player, target) != before-2 || after != 1 || g.Counters[shield].Value != 2 {
					t.Fatal("piercing must deal exactly 2, emit damage, and preserve crystal shield")
				}
				for i, id := range uses {
					if g.Counters[id].Value != 1 {
						t.Fatalf("piercing consumed modifier at stage %v", stages[i])
					}
				}
				// The same defenses must still run for the following ordinary hit.
				before = env.HP(player, target)
				nativeDamage(env, player, target, engine.ElemPhysical, 2)
				if env.HP(player, target) != before {
					t.Fatal("ordinary damage bypassed immunity")
				}
				for i, id := range uses {
					if g.Counters[id].Value != 0 {
						t.Fatalf("ordinary damage failed to run stage %v", stages[i])
					}
				}
			})
		}
	}
}
