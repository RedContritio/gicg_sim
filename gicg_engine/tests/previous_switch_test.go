package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestPreviousSwitchCyclesAndSkipsDefeated(t *testing.T) {
	for _, player := range []int{0, 1} {
		for _, remaining := range []int{1, 2, 3} {
			t.Run(fmt.Sprintf("player%d_alive%d", player, remaining), func(t *testing.T) {
				team := []string{"赤蝶", "墨客", "猫咪"}
				env := NewGame(t, team, team)
				g := env.G
				g.Players[player].ActiveChar = 0
				for c := remaining; c < 3; c++ {
					g.Players[player].Chars[c].Alive = false
				}
				calls := 0
				g.Hooks.Register(engine.Hook{Type: engine.HookSwitch, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
					calls++
					if ctx.ActorPlayer != player || ctx.ActionCtx != engine.ActForcedReaction {
						t.Fatalf("wrong forced-switch context: %+v", ctx)
					}
				}})
				before := g.Turn
				run := func() {
					src := fmt.Sprintf("force_switch_previous(%d)", player)
					if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
						t.Fatal(err)
					}
				}
				run()
				wantCalls := 1
				if remaining == 1 {
					wantCalls = 0
				}
				if g.Players[player].ActiveChar != remaining-1 || calls != wantCalls || g.Turn != before {
					t.Fatalf("active=%d calls=%d", g.Players[player].ActiveChar, calls)
				}
				if remaining == 3 {
					run()
					if g.Players[player].ActiveChar != 1 || calls != 2 {
						t.Fatal("must cycle 0 → 2 → 1, not forward")
					}
				}
			})
		}
	}
}
