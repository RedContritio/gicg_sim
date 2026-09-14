package tests

import (
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestLifecycle_PreparingSupportsAndPendingIsolation(t *testing.T) {
	for _, pooled := range []bool{false, true} {
		t.Run(map[bool]string{false: "full", true: "pooled"}[pooled], func(t *testing.T) {
			env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
			g := env.G
			g.Preparing = [2]int{17, 29}
			g.PendingReactionKind = 3
			g.Players[0].Supports = []engine.SupportInst{{Ref: 42, ActivatedAt: 1}}
			g.PendingAction = &engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 1,
				Forced: true, AppliedMods: map[int]bool{7: true}}
			g.PendingCardTarget = &engine.PendingCard{PlayerIdx: 0, CardRef: 23, TargetMode: 1}
			var restore func()
			if pooled {
				s := g.SnapshotPooled()
				defer engine.ReleaseSnap(s)
				restore = func() { g.RestoreFromSnap(s) }
			} else {
				s := g.DeepCopy()
				restore = func() { g.RestoreFrom(s) }
			}
			for attempt := 0; attempt < 3; attempt++ {
				g.Preparing = [2]int{}
				g.PendingReactionKind = 0
				g.Players[0].Supports[0].Ref = 99
				g.Players[1].Supports = []engine.SupportInst{{Ref: 99}}
				g.PendingAction.PlayerIdx = 0
				g.PendingAction.AppliedMods[7] = false
				g.PendingCardTarget.CardRef = 99
				restore()
				if g.Preparing != [2]int{17, 29} || g.PendingReactionKind != 3 {
					t.Fatal("transient gameplay fields were not restored")
				}
				if g.Players[0].Supports[0].Ref != 42 || len(g.Players[1].Supports) != 0 {
					t.Fatal("support state was not restored")
				}
				if g.PendingAction.PlayerIdx != 1 || !g.PendingAction.AppliedMods[7] || g.PendingCardTarget.CardRef != 23 {
					t.Fatal("snapshot was contaminated through pending state")
				}
			}
		})
	}
}

func TestLifecycle_SpecialtyActualPlayCloneRestoreReset(t *testing.T) {
	env := NewGameWithDeck(t, []string{"玛薇卡"}, []string{"玛薇卡"})
	g := env.G
	ref := env.RT.Cards.ByName["驰轮车_疾驰"].Ref
	g.SetPlayerHand(0, []int{ref})
	before := g.DeepCopy()
	pooled := g.SnapshotPooled()
	defer engine.ReleaseSnap(pooled)
	clone := env.RT.Clone()
	play := func(game *engine.Game) {
		t.Helper()
		for i, a := range game.GetLegalActions() {
			if a.Kind == engine.ActionCard && a.Index == 0 {
				game.Step(i)
				if game.Players[0].Chars[0].SpecialtyCardRef != ref {
					t.Fatal("equip did not resolve")
				}
				return
			}
		}
		t.Fatal("specialty card unavailable")
	}
	play(clone.Game)
	if g.Players[0].Chars[0].SpecialtyCardRef != -1 {
		t.Fatal("clone changed live equipment")
	}
	play(g)
	g.RestoreFrom(before)
	play(g)
	g.RestoreFromSnap(pooled)
	play(g)
	env.RT.ResetDynamic(42)
	if g.Players[0].Chars[0].SpecialtyCardRef != -1 {
		t.Fatal("equipment leaked across reset")
	}
	g.SetPlayerHand(0, []int{ref})
	play(g)
}

func TestLifecycle_ResetMatchesFreshGame(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	fresh := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	g := env.G
	g.Preparing[0] = 999
	g.PendingReactionKind = 7
	g.Players[1].Supports = []engine.SupportInst{{Ref: 7}}
	g.Players[0].Chars[0].SpecialtyCardRef = 8
	g.PendingAction = &engine.Action{Kind: engine.ActionSwitch}
	for i := 0; i < 5; i++ {
		g.Rng.Int63()
		g.DeckRngs[0].Int63()
	}
	env.RT.ResetDynamic(42)
	// Slice capacity and nil-vs-empty are allocation details, not game state.
	players := g.Players
	for pi := range players {
		players[pi].Supports = append([]engine.SupportInst(nil), players[pi].Supports...)
		players[pi].Discard = append([]engine.CardInst(nil), players[pi].Discard...)
	}
	if !reflect.DeepEqual(players, fresh.G.Players) {
		t.Fatalf("reset players=%+v fresh=%+v", players, fresh.G.Players)
	}
	if !reflect.DeepEqual(g.Counters, fresh.G.Counters) {
		for i, c := range g.Counters {
			if c != fresh.G.Counters[i] {
				t.Errorf("counter %d: reset=%+v fresh=%+v", i, c, fresh.G.Counters[i])
			}
		}
	}
	if g.Preparing != [2]int{} || g.PendingReactionKind != 0 || g.PendingAction != nil {
		t.Fatal("reset left pending gameplay state")
	}
	for i := 0; i < 20; i++ {
		if g.Rng.Uint64() != fresh.G.Rng.Uint64() {
			t.Fatal("reset RNG differs from fresh game")
		}
		for pi := 0; pi < 2; pi++ {
			if g.DeckRngs[pi].Uint64() != fresh.G.DeckRngs[pi].Uint64() {
				t.Fatal("reset deck RNG differs")
			}
		}
	}
}

func TestLifecycle_InvalidPendingTargetPreservesChoice(t *testing.T) {
	env := NewGame(t, []string{"赤蝶", "墨客"}, []string{"刻师傅"})
	g := env.G
	g.PendingAction = &engine.Action{Kind: engine.ActionSwitch, PlayerIdx: 0, Forced: true}
	g.StepTarget(-1)
	if g.PendingAction == nil {
		t.Fatal("invalid target discarded pending switch")
	}
	g.PendingAction = nil
	g.PendingCardTarget = &engine.PendingCard{PlayerIdx: 0, TargetMode: 1, CardRef: -1}
	g.StepTarget(-1)
	if g.PendingCardTarget == nil {
		t.Fatal("invalid target discarded pending card")
	}
}
