package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestOverloadBuiltinSwitchesBothPerspectives(t *testing.T) {
	for _, target := range []int{0, 1} {
		for _, single := range []bool{false, true} {
			t.Run(fmt.Sprintf("target%d_single%v", target, single), func(t *testing.T) {
				env := NewGameWithDeck(t, []string{"赤蝶", "墨客"}, []string{"赤蝶", "墨客"})
				g := env.G
				if single {
					g.Players[target].Chars[1].Alive = false
				}
				src := fmt.Sprintf(`get_counter("雷元素附着", Scope.PerChar):set_at(%d, 0, 1)`, target)
				if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
					t.Fatal(err)
				}
				hp := env.RT.Chars.BySlot[target][0].HPCounterID
				before := g.Counters[hp].Value
				reaction := -1
				switches := 0
				g.Hooks.Register(engine.Hook{Type: engine.HookSwitch, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
					switches++
					if ctx.ActorPlayer != target || ctx.ActorChar != 1 || ctx.ActionCtx != engine.ActForcedReaction {
						t.Fatalf("wrong forced switch context: %+v", ctx)
					}
				}})
				g.Hooks.Register(engine.Hook{Type: engine.HookAfterDamage, Priority: 1000,
					Fn: func(_ *engine.Game, ctx *engine.EventContext) { reaction = ctx.ReactionKind }})
				g.PushEvent(engine.EventFrame{ActionCtx: engine.ActUseSkill, Player: 1 - target, Char: 0})
				g.DealDamage(hp, engine.ElemFire, 2, engine.DamageOpts{ActorPlayer: 1 - target, ActorChar: 0})
				g.PopEvent()
				want := 1
				if single {
					want = 0
				}
				if g.Players[target].ActiveChar != want || g.Players[1-target].ActiveChar != 0 {
					t.Fatal("overload switched the wrong player/character")
				}
				if switches != want {
					t.Fatalf("got %d switch events, want %d", switches, want)
				}
				if before-g.Counters[hp].Value != 4 || reaction != g.ReactionRegistry["Overload"] {
					t.Fatalf("damage=%d reaction=%d", before-g.Counters[hp].Value, reaction)
				}
			})
		}
	}
}
