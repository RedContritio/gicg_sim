package tests

import (
	"bytes"
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

func fullNativeSupportZone(t *testing.T, p int) *GameEnv {
	t.Helper()
	e := nativeTalentGame(t, "凯亚")
	for _, card := range []string{"派蒙", "鸣神大社", "派蒙", "鸣神大社"} {
		e.SetDice(p, map[int]int{engine.DiceColorOmni: 16})
		auditPlay(t, e, p, card)
	}
	e.SetDice(p, map[int]int{engine.DiceColorOmni: 16})
	e.G.Turn = p
	// Inject a further copy to exercise generic zone replacement independently
	// of deck construction (this starter pool has only two support definitions).
	e.giveCard(t, p, "派蒙")
	return e
}

func TestNativeSupportReplacementChoosesExactlyOneInstance(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprintf("P%d", p), func(t *testing.T) {
			e := fullNativeSupportZone(t, p)
			before := checkpointBytes(t, e.G)
			choices := 0
			for index, action := range e.G.GetLegalActions() {
				if !action.HasSupportTarget {
					continue
				}
				choices++
				if engine.ActionCharRef(action) != -2-engine.ObsBuffRows-action.TargetSupport {
					t.Fatal("wrong target reference")
				}
				old := e.G.Players[p].Supports[action.TargetSupport]
				clone := e.RT.Clone()
				branch := &GameEnv{G: clone.Game, RT: clone, T: t}
				replay := e.RT.Clone()
				input := engine.InputForAction(action)
				replayer := record.Replayer{Runtime: replay, Rec: &record.Record{Rounds: []record.Round{{
					Number: 1, Actions: []record.Action{{Kind: record.ActCard, Player: p, Name: "派蒙", Input: &input, TargetPlayer: -1}},
				}}}}
				if err := replayer.Step(1, 0); err != nil {
					t.Fatal(err)
				}
				if branch.G.Step(index) != engine.StepContinue || branch.DiceTotal(p) != 13 || branch.G.Turn != p {
					t.Fatal("replacement paid incorrectly or lost fast action")
				}
				if !bytes.Equal(checkpointBytes(t, replay.Game), checkpointBytes(t, branch.G)) {
					t.Fatal("record replay diverged from selected replacement")
				}
				zone := branch.G.Players[p].Supports
				if len(zone) != 4 || zone[3].ID == old.ID || zone[3].BuffID == old.BuffID || zone[3].Ref != e.cardRef("派蒙") {
					t.Fatal("new support did not enter with its own fresh state")
				}
				for _, support := range zone {
					if support.ID == old.ID {
						t.Fatal("selected old support survived")
					}
				}
				if counter, _ := branch.G.SelectedBuffCounter(old.BuffID); counter != -1 {
					t.Fatal("removed support effect survived")
				}
				if err := branch.G.RestoreCheckpoint(checkpointBytes(t, branch.G)); err != nil {
					t.Fatal(err)
				}
			}
			if choices != 4 {
				t.Fatalf("replacement choices=%d, want four", choices)
			}
			if !bytes.Equal(before, checkpointBytes(t, e.G)) {
				t.Fatal("enumeration or clone mutated source")
			}
		})
	}
}

func TestNativeReplacementKeepsIdentityWhenPaymentRemovesEarlierSlot(t *testing.T) {
	e := fullNativeSupportZone(t, 0)
	selected := e.G.Players[0].Supports[3]
	e.G.Hooks.Register(engine.Hook{Type: engine.HookActionPrepare,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			// The execution-only prepare pass runs after payment; enumeration
			// has no ActPlayCard context and must remain read-only.
			if ctx.ActionCtx == engine.ActPlayCard {
				g.RemoveSupportAt(0, 0)
			}
		}})
	for index, action := range e.G.GetLegalActions() {
		if action.HasSupportTarget && action.TargetSupport == 3 {
			e.G.Step(index)
			if len(e.G.Players[0].Supports) != 3 {
				t.Fatal("replacement did not account for payment removal")
			}
			for _, support := range e.G.Players[0].Supports {
				if support.ID == selected.ID {
					t.Fatal("slot shift changed selected support")
				}
			}
			return
		}
	}
	t.Fatal("replacement action absent")
}
