package tests

import (
	"fmt"
	"testing"
)

func nativeNextRound(t *testing.T, e *GameEnv) {
	t.Helper()
	e.playToRoundEnd(t)
	e.G.GetLegalActions()
}

func TestNativePaimonCopiesHaveIndependentLifetimes(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprintf("P%d", p), func(t *testing.T) {
			e := nativeTalentGame(t, "凯亚")
			auditPlay(t, e, p, "派蒙")
			first := e.G.Players[p].Supports[0].BuffID
			if first == 0 || e.DiceTotal(p) != 13 {
				t.Fatal("support was not bound or paid correctly")
			}
			nativeNextRound(t, e)
			if e.DiceTotal(p) != 10 || len(e.G.Players[p].Supports) != 1 {
				t.Fatal("first Paimon must add two dice and retain one use")
			}
			auditPlay(t, e, p, "派蒙")
			second := e.G.Players[p].Supports[1].BuffID
			if second == 0 || second == first {
				t.Fatal("same-name supports share lifecycle identity")
			}
			clone := e.RT.Clone()
			branch := &GameEnv{G: clone.Game, RT: clone, T: t}
			checkpoint, err := e.G.ExportCheckpoint()
			if err != nil {
				t.Fatal(err)
			}
			if err := branch.G.RestoreCheckpoint(checkpoint); err != nil {
				t.Fatalf("support checkpoint could not be restored: %v", err)
			}
			nativeNextRound(t, branch)
			if branch.DiceTotal(p) != 12 || len(branch.G.Players[p].Supports) != 1 ||
				branch.G.Players[p].Supports[0].BuffID != second {
				t.Fatal("older Paimon must expire without removing or refreshing the newer copy")
			}
			if len(e.G.Players[p].Supports) != 2 || e.G.Round == branch.G.Round {
				t.Fatal("clone mutated source support state")
			}
			nativeNextRound(t, branch)
			if branch.DiceTotal(p) != 10 || len(branch.G.Players[p].Supports) != 0 {
				t.Fatal("newer Paimon must expire after its own second use")
			}
			nativeNextRound(t, branch)
			if branch.DiceTotal(p) != 8 {
				t.Fatal("expired supports still generate dice")
			}
		})
	}
}

func TestNativeSupportRemovalClearsOnlyAssociatedEffect(t *testing.T) {
	e := nativeTalentGame(t, "凯亚")
	auditPlay(t, e, 0, "派蒙")
	auditPlay(t, e, 0, "派蒙")
	second := e.G.Players[0].Supports[1].BuffID
	if err := e.RT.Interp.ExecFile(e.RT, []byte(`remove_support(0, get_card("派蒙"))`), e.RT.Interp.Global); err != nil {
		t.Fatal(err)
	}
	if len(e.G.Players[0].Supports) != 1 || e.G.Players[0].Supports[0].BuffID != second {
		t.Fatal("external removal did not preserve other support")
	}
	nativeNextRound(t, e)
	if e.DiceTotal(0) != 10 {
		t.Fatal("removed support effect survived or remaining effect was removed")
	}
	// Reset must clear both the zone and the independently stored effect.
	e.RT.ResetDynamic(42)
	if len(e.G.Players[0].Supports) != 0 || len(e.G.Buffs) != 0 {
		t.Fatal("reset retained support instance state")
	}
}
