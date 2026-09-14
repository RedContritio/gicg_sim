package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestSetActiveCharDispatchesOnceAndDrainsEffects(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶", "墨客"}, []string{"赤蝶", "墨客"})
	g := env.G
	beforeTurn := g.Turn
	beforeDice := env.RT.DicePool(0)
	calls, deferred := 0, 0
	g.Hooks.Register(engine.Hook{Type: engine.HookSwitch, Fn: func(game *engine.Game, ctx *engine.EventContext) {
		calls++
		if ctx.ActorPlayer != 0 || ctx.ActorChar != 1 || ctx.ActionCtx != engine.ActForcedReaction {
			t.Fatalf("unexpected switch context: %+v", ctx)
		}
		game.Defer(func(inner *engine.Game) {
			deferred++
			if inner.CurrentEvent().Player != 0 {
				t.Fatal("deferred switch effect lost perspective")
			}
		})
	}})
	src := `set_active_char(0, 1)
set_active_char(0, 1)`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatal(err)
	}
	if calls != 1 || deferred != 1 || g.Turn != beforeTurn || env.RT.DicePool(0) != beforeDice {
		t.Fatalf("events=%d deferred=%d turn=%d", calls, deferred, g.Turn)
	}
}

func TestSwitchOperationIsDistinctFromCharacterChanged(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶", "墨客"}, []string{"赤蝶", "墨客"})
	g := env.G
	changes, operations := 0, 0
	g.Hooks.Register(engine.Hook{Type: engine.HookSwitch, Fn: func(_ *engine.Game, ctx *engine.EventContext) {
		changes++
		if ctx.ActionCtx == engine.ActSwitch {
			operations++
		}
	}})
	g.ForceSwitchTo(0, 1)
	g.ForceSwitchTo(0, 1) // No actual change: neither semantic event fires.
	if changes != 1 || operations != 0 {
		t.Fatalf("forced change counted as an operation: changes=%d operations=%d", changes, operations)
	}
	index := -1
	for i, action := range g.GetLegalActions() {
		if action.Kind == engine.ActionSwitch && !action.Forced {
			index = i
			break
		}
	}
	if index < 0 {
		t.Fatal("missing voluntary switch")
	}
	g.Step(index)
	if changes != 2 || operations != 1 {
		t.Fatalf("voluntary switch must satisfy both: changes=%d operations=%d", changes, operations)
	}
}

func TestForceSwitchEffectResumesAfterDeathChoice(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶", "墨客"}, []string{"墨客", "赤蝶"})
	g := env.G
	reactionEvents := g.CreateCounter(0, 0, 10)
	deathEvents := g.CreateCounter(0, 0, 10)
	tail := g.CreateCounter(0, 0, 10)
	hp := env.RT.Chars.BySlot[1][0].HPCounterID
	g.Hooks.Register(engine.Hook{Type: engine.HookSwitch, Fn: func(game *engine.Game, ctx *engine.EventContext) {
		if ctx.ActionCtx == engine.ActForcedReaction {
			game.WriteCounter(reactionEvents, engine.OpAdd, 1)
			game.DealDamage(hp, engine.ElemPhysical, 99, engine.DamageOpts{ActorPlayer: 0, ActorChar: 1})
		} else if ctx.ActionCtx == engine.ActForcedDeath {
			game.WriteCounter(deathEvents, engine.OpAdd, 1)
		}
	}})
	result := g.ExecuteEffect(engine.EventFrame{Player: 0, Char: 0, Source: engine.SrcCard}, func(game *engine.Game) {
		game.ForceSwitchTo(0, 1)
		game.WriteCounter(tail, engine.OpAdd, 1)
	})
	if result != engine.StepNeedTarget || g.Counters[reactionEvents].Value != 1 || g.Counters[tail].Value != 0 {
		t.Fatal("forced switch effect did not suspend at the death choice")
	}
	snap := g.SnapshotPooled()
	defer engine.ReleaseSnap(snap)
	branch := env.RT.Clone().Game
	for _, game := range []*engine.Game{branch, g, g} {
		if game == g {
			g.RestoreFromSnap(snap)
		}
		game.StepTarget(0)
		if game.Counters[reactionEvents].Value != 1 || game.Counters[deathEvents].Value != 1 ||
			game.Counters[tail].Value != 1 || !game.IsQuiescent() {
			t.Fatal("clone/restore repeated or lost a forced switch effect")
		}
	}
}
