package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"reflect"
	"testing"
)

func TestLethalOverloadAutomaticallySwitchesNext(t *testing.T) {
	for _, target := range []int{0, 1} {
		for _, count := range []int{1, 2, 3} {
			t.Run(fmt.Sprintf("target%d_count%d", target, count), func(t *testing.T) {
				team := []string{"赤蝶", "墨客", "猫咪"}[:count]
				env := NewGameWithDeck(t, team, team)
				g := env.G
				src := fmt.Sprintf(`get_counter("雷元素附着", Scope.PerChar):set_at(%d, 0, 1)`, target)
				if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
					t.Fatal(err)
				}
				death := g.CreateCounter(0, 0, 10)
				reaction := g.CreateCounter(0, 0, 10)
				g.Hooks.Register(engine.Hook{Type: engine.HookSwitch, Fn: func(game *engine.Game, ctx *engine.EventContext) {
					if ctx.ActionCtx == engine.ActForcedDeath {
						game.WriteCounter(death, engine.OpAdd, 1)
					}
					if ctx.ActionCtx == engine.ActForcedReaction {
						game.WriteCounter(reaction, engine.OpAdd, 1)
					}
				}})
				hp := env.RT.Chars.BySlot[target][0].HPCounterID
				turn, dice := g.Turn, g.DicePaid
				result := g.ExecuteEffect(engine.EventFrame{Player: 1 - target, Char: 0, ActionCtx: engine.ActUseSkill}, func(game *engine.Game) {
					game.DealDamage(hp, engine.ElemFire, 99, engine.DamageOpts{ActorPlayer: 1 - target, ActorChar: 0})
				})
				if count == 1 {
					if g.Phase != engine.PhaseGameOver || g.Winner != 1-target || g.PendingAction != nil {
						t.Fatal("last death did not finish")
					}
					return
				}
				if result != engine.StepContinue || g.HasPending() || g.Players[target].ActiveChar != 1 || !g.IsQuiescent() {
					t.Fatal("lethal overload did not automatically choose next living character")
				}
				if g.Counters[death].Value != 0 || g.Counters[reaction].Value != 1 {
					t.Fatal("automatic overload switch should dispatch exactly one reaction switch")
				}
				if g.Turn != turn || !reflect.DeepEqual(g.DicePaid, dice) {
					t.Fatal("automatic overload switch changed turn/dice")
				}
			})
		}
	}
}
