package tests

import (
	"bytes"
	"encoding/json"
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestTargetFrameCheckpointAndExactlyOnce(t *testing.T) {
	e := NewGame(t, []string{"赤蝶", "墨客"}, []string{"刻师傅"})
	g := e.G
	ref := e.RT.Cards.ByName["碌碌无为"].Ref
	marker := g.CreateCounter(0, 0, 10)
	g.Hooks.Register(engine.Hook{Type: engine.HookRoundStart, OwnerPlayer: 0,
		Fn: func(g *engine.Game, _ *engine.EventContext) { g.SetPlayerHand(0, []int{ref, ref}) }})
	mod := g.CanonicalCardHooks[ref]
	g.Hooks.Register(engine.Hook{Type: engine.HookActionPrepare,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.ActionKind == engine.ActionCard && ctx.CardRef == ref {
				ctx.AppliedMods = map[int]bool{mod: true}
				if ctx.ActionCtx == engine.ActPlayCard {
					ctx.NeedTarget, ctx.TargetMode = true, 1
				}
			}
		}})
	g.Hooks.Register(engine.Hook{Type: engine.HookCardPlay,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.CardRef == ref && ctx.AppliedMods[mod] {
				g.WriteCounter(marker, engine.OpAdd, ctx.TargetChar+1)
			}
		}})
	e.RT.ResetDynamic(42)
	receiver := e.RT.Clone()
	initialDice := e.RT.DicePool(0)
	if g.Step(e.FindAction(engine.ActionCard, "碌碌无为")) != engine.StepNeedTarget {
		t.Fatal("card did not suspend")
	}
	paidDice := e.RT.DicePool(0)
	spent := 0
	for i := range initialDice {
		spent += initialDice[i] - paidDice[i]
	}
	if spent != 1 {
		t.Fatal("fixture must pay the card's one-die cost before suspension", spent)
	}
	frame := g.PendingCardTarget
	before := checkpointBytes(t, g)
	for _, index := range []int{-1, 99} {
		g.StepTarget(index)
		if !bytes.Equal(before, checkpointBytes(t, g)) {
			t.Fatal("invalid target mutated paid state")
		}
	}
	if err := receiver.Game.RestoreCheckpoint(before); err != nil {
		t.Fatal(err)
	}
	receiver.Game.PendingCardTarget.AppliedMods[mod] = false
	if !frame.AppliedMods[mod] {
		t.Fatal("restored modifier map aliases source")
	}
	if err := receiver.Game.RestoreCheckpoint(before); err != nil {
		t.Fatal(err)
	}
	g.StepTarget(1)
	receiver.Game.StepTarget(1)
	if e.RT.DicePool(0) != paidDice || receiver.DicePool(0) != paidDice {
		t.Fatal("target selection paid the card cost twice")
	}
	if frame.PC != engine.TargetConsumed || g.Counters[marker].Value != 2 ||
		len(g.Players[0].Hand) != 1 || len(g.Players[0].Discard) != 1 {
		t.Fatal("paid card was not consumed exactly once")
	}
	if !bytes.Equal(checkpointBytes(t, g), checkpointBytes(t, receiver.Game)) {
		t.Fatal("restored frame diverged")
	}
	// A retained pointer cannot invoke the paid card for a second time.
	func() {
		defer func() {
			if recover() == nil {
				t.Fatal("consumed frame accepted")
			}
		}()
		frame.Resume(g, 0)
	}()
	if g.Counters[marker].Value != 2 {
		t.Fatal("stale frame repeated effect")
	}
}

func TestTargetFrameObservationVisibilityAndValidation(t *testing.T) {
	e := currentCardGame(t, 0)
	g := e.G
	ref := e.RT.Cards.ByName["碌碌无为"].Ref
	mod := g.CanonicalCardHooks[ref]
	g.PendingCardTarget = &engine.TargetFrame{PlayerIdx: 0, CardRef: ref, TargetMode: 1,
		AppliedMods: map[int]bool{mod: true}}
	rows := entityRows(g, 0, engine.EntityExecutionFrame)
	bindings := entityRows(g, 0, engine.EntityExecutionBinding)
	if len(rows) != 1 || rows[0][3] != 1 || rows[0][7] < 0 || rows[0][4] != 1 ||
		len(bindings) != 1 || bindings[0][7] != rows[0][7] {
		t.Fatal("missing program/rule/locals", rows, bindings)
	}
	other := g.BuildDynamicObs(1)
	g.PendingCardTarget.AppliedMods = map[int]bool{999999: true}
	if !reflect.DeepEqual(other, g.BuildDynamicObs(1)) || len(entityRows(g, 1, engine.EntityExecutionBinding)) != 0 {
		t.Fatal("private applied conditions leaked to opponent")
	}
	if entityRows(g, 0, engine.EntityExecutionFrame)[0][3] != 0 || len(entityRows(g, 0, engine.EntityExecutionBinding)) != 0 {
		t.Fatal("opaque native rule pretended complete")
	}
	g.PendingCardTarget.AppliedMods = map[int]bool{mod: true}
	before := checkpointBytes(t, g)
	for key, value := range map[string]any{"PC": 1, "PlayerIdx": 2, "CardRef": 999999, "TargetMode": 0, "AppliedMods": map[string]bool{"999999": true}} {
		var wire map[string]any
		if err := json.Unmarshal(before, &wire); err != nil {
			t.Fatal(err)
		}
		wire["State"].(map[string]any)["PendingCardTarget"].(map[string]any)[key] = value
		bad, _ := json.Marshal(wire)
		if g.RestoreCheckpoint(bad) == nil || !bytes.Equal(before, checkpointBytes(t, g)) {
			t.Fatal("invalid frame import was not rejected atomically", key)
		}
	}
	for _, oldVersion := range []bool{false, true} {
		var wire map[string]any
		if err := json.Unmarshal(before, &wire); err != nil {
			t.Fatal(err)
		}
		if oldVersion {
			wire["Version"] = 1
		} else {
			wire["State"].(map[string]any)["Phase"] = engine.PhaseRoundStart
		}
		bad, _ := json.Marshal(wire)
		if g.RestoreCheckpoint(bad) == nil || !bytes.Equal(before, checkpointBytes(t, g)) {
			t.Fatal("incompatible checkpoint accepted")
		}
	}
}

func TestTargetFrameRestoresIntoFreshRuntime(t *testing.T) {
	source := currentCardGame(t, 0)
	receiver := currentCardGame(t, 0)
	ref := source.RT.Cards.ByName["铁枪"].Ref
	// An explicit already-paid state: its source runtime and hooks are never
	// shared with the receiver. The native legacy-path test covers reaching it.
	source.G.PendingCardTarget = &engine.TargetFrame{PlayerIdx: 0, CardRef: ref, TargetMode: 1}
	source.G.Players[0].Discard = append(source.G.Players[0].Discard, engine.CardInst{Ref: ref})
	state := checkpointBytes(t, source.G)
	if err := receiver.G.RestoreCheckpoint(state); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(source.G.GetLegalActions(), receiver.G.GetLegalActions()) {
		t.Fatal("restored target legality differs")
	}
	source.G.StepTarget(0)
	receiver.G.StepTarget(0)
	if source.G.PendingCardTarget != nil || !bytes.Equal(checkpointBytes(t, source.G), checkpointBytes(t, receiver.G)) {
		t.Fatal("independent-runtime continuation diverged")
	}
}
