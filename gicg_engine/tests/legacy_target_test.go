package tests

import (
	"bytes"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

func TestLegacyTarget_StepAndStepTargetPreserveModifiers(t *testing.T) {
	for _, useStep := range []bool{false, true} {
		t.Run(map[bool]string{false: "target", true: "step"}[useStep], func(t *testing.T) {
			env := NewGame(t, []string{"赤蝶", "墨客"}, []string{"刻师傅"})
			g := env.G
			ref := env.RT.Cards.ByName["碌碌无为"].Ref
			marker := g.CreateCounter(0, 0, 10)
			g.Hooks.Register(engine.Hook{Type: engine.HookRoundStart, OwnerPlayer: 0,
				Fn: func(g *engine.Game, _ *engine.EventContext) { g.SetPlayerHand(0, []int{ref, ref}) }})
			g.Hooks.Register(engine.Hook{Type: engine.HookActionPrepare,
				Fn: func(g *engine.Game, ctx *engine.EventContext) {
					if ctx.ActionKind != engine.ActionCard || ctx.CardRef != ref {
						return
					}
					if ctx.AppliedMods == nil {
						ctx.AppliedMods = map[int]bool{}
					}
					ctx.AppliedMods[777] = true
					// Exercise the documented compatibility path: target declared
					// at execution time, rather than in action enumeration.
					if ctx.ActionCtx == engine.ActPlayCard {
						ctx.NeedTarget, ctx.TargetMode = true, 1
					}
				}})
			g.Hooks.Register(engine.Hook{Type: engine.HookActionCheck,
				Fn: func(g *engine.Game, ctx *engine.EventContext) {
					if ctx.CardRef == ref && ctx.TargetPlayer >= 0 && !ctx.AppliedMods[777] {
						ctx.Playable = false
					}
				}})
			g.Hooks.Register(engine.Hook{Type: engine.HookCardPlay,
				Fn: func(g *engine.Game, ctx *engine.EventContext) {
					if ctx.CardRef == ref && ctx.AppliedMods[777] {
						g.WriteCounter(marker, engine.OpAdd, ctx.TargetChar+1)
					}
				}})
			env.RT.ResetDynamic(42)
			receiver := env.RT.Clone()
			if g.Step(env.FindAction(engine.ActionCard, "碌碌无为")) != engine.StepNeedTarget {
				t.Fatal("legacy card did not request a target")
			}
			if len(g.GetLegalActions()) != 2 {
				t.Fatal("target checks lost applied modifiers")
			}
			unfinished, err := record.Parse(record.Export(env.RT))
			if err != nil {
				t.Fatal(err)
			}
			if err := record.ReplayTo(receiver, unfinished, 1); err != nil {
				t.Fatal(err)
			}
			if receiver.Game.PendingCardTarget == nil || receiver.Game.Counters[marker].Value != 0 {
				t.Fatal("replaying an unfinished card invented a target")
			}
			snap := g.SnapshotPooled()
			defer engine.ReleaseSnap(snap)
			g.PendingCardTarget.AppliedMods[777] = false
			g.RestoreFromSnap(snap)
			if !g.PendingCardTarget.AppliedMods[777] {
				t.Fatal("snapshot aliased the pending modifier map")
			}
			for repeat := 0; repeat < 2; repeat++ {
				g.RestoreFromSnap(snap)
				if useStep {
					g.Step(1)
				} else {
					g.StepTarget(1)
				}
				if g.PendingCardTarget != nil || g.Counters[marker].Value != 2 || len(g.Players[0].Hand) != 1 || len(g.Players[0].Discard) != 1 {
					t.Fatal("target did not resolve exactly once with original modifiers")
				}
			}
			rec, err := record.Parse(record.Export(env.RT))
			if err != nil {
				t.Fatal(err)
			}
			if record.TotalSteps(rec) != 1 {
				t.Fatal("target selection was incorrectly logged as another card play")
			}
			if err := record.ReplayTo(receiver, rec, 1); err != nil {
				t.Fatal(err)
			}
			want, err := g.ExportCheckpoint()
			if err != nil {
				t.Fatal(err)
			}
			got, err := receiver.Game.ExportCheckpoint()
			if err != nil || !bytes.Equal(got, want) {
				t.Fatalf("legacy target replay differs: %v", err)
			}
		})
	}
}
