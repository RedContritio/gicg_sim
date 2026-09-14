package tests

import (
	"encoding/json"
	"fmt"
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

func TestDiceSelectionConfirmAndBranchRandomness(t *testing.T) {
	for _, player := range []int{0, 1} {
		e := nativeTalentGame(t, "凯亚")
		e.SetDice(player, map[int]int{engine.DiceColorFire: 2, engine.DiceColorOmni: 1})
		g := e.G
		marker := g.CreateCounter(0, 0, 10)
		before := e.RT.DicePool(player)
		rng := g.Rng.Clone()
		if g.ExecuteEffect(engine.EventFrame{Player: player}, func(g *engine.Game) {
			g.ChooseReroll(player, 2)
			g.WriteCounter(marker, engine.OpAdd, 1)
		}) != engine.StepNeedTarget || g.ActingPlayer() != player || !g.HasPending() {
			t.Fatal("reroll did not expose owner decision")
		}
		if len(g.GetLegalActions()) != 3 || g.PendingDice.Color != engine.DiceColorFire {
			t.Fatal("missing count choices")
		}
		g.Step(2)       // select two fire
		g.StepTarget(0) // retain omni
		if g.PendingDice.Color != engine.DiceColorCount || e.RT.DicePool(player) != before || g.Rng.Clone().Int63() != rng.Int63() {
			t.Fatal("selection changed dice/randomness before confirmation")
		}
		for _, seed := range []int64{13, 27, 13} {
			branch := e.RT.Clone()
			branch.Game.SetSimulationSeed(seed)
			expected := [engine.DiceColorCount]int{engine.DiceColorOmni: 1}
			random := branch.Game.Rng.Clone()
			for range 2 {
				expected[random.Intn(engine.DiceColorCount)]++
			}
			branch.Game.Step(0) // first confirmation
			if branch.DicePool(player) != expected || branch.Game.PendingDice.Remaining != 1 {
				t.Fatal("confirmation lost branch RNG or second choice")
			}
			// Second selection may include the omni retained in the first.
			for branch.Game.PendingDice != nil {
				f := branch.Game.PendingDice
				count := 0
				if f.Color == engine.DiceColorOmni {
					count = f.Pool[f.Color]
				}
				branch.Game.Step(count)
			}
			if branch.Game.Counters[marker].Value != 1 || branch.Game.HasPending() {
				t.Fatal("enclosing effect did not resume once")
			}
			total := 0
			for _, count := range branch.DicePool(player) {
				total += count
			}
			if total != 3 {
				t.Fatal("reroll changed total dice")
			}
		}
		if e.RT.DicePool(player) != before || g.PendingDice.Color != engine.DiceColorCount || g.Counters[marker].Value != 0 {
			t.Fatal("branch mutated source")
		}
		snap := g.SnapshotPooled()
		g.PendingDice.Selected[0] = 0
		g.RestoreFromSnap(snap)
		if !reflect.DeepEqual(g.PendingDice.Selected, snap.PendingDice.Selected) || g.PendingDice.Selected[0] != 2 {
			t.Fatal("snapshot aliased pending selection")
		}
		engine.ReleaseSnap(snap)
		g.ResetDynamicState(5)
		if g.PendingDice != nil || g.HasPending() {
			t.Fatal("reset retained selection")
		}
	}
}

func TestEmptyRerollAndInvalidChoiceAreReadOnly(t *testing.T) {
	e := nativeTalentGame(t, "凯亚")
	e.SetDice(0, map[int]int{})
	g := e.G
	g.ExecuteEffect(engine.EventFrame{Player: 0}, func(g *engine.Game) { g.ChooseReroll(0, 2) })
	random := g.Rng.Clone()
	g.Step(-1)
	g.Step(1)
	if g.PendingDice == nil || g.PendingDice.Remaining != 2 || len(g.GetLegalActions()) != 1 {
		t.Fatal("invalid choice consumed a reroll")
	}
	g.Step(0)
	g.Step(0)
	if g.HasPending() || g.Rng.Int63() != random.Int63() {
		t.Fatal("empty reroll consumed random state or did not finish")
	}
}

func TestDiceSelectionObservationAndRecordedReplay(t *testing.T) {
	e := nativeTalentGame(t, "凯亚")
	e.SetDice(0, map[int]int{engine.DiceColorFire: 2, engine.DiceColorOmni: 1})
	g := e.G
	g.ExecuteEffect(engine.EventFrame{Player: 0}, func(g *engine.Game) { g.ChooseReroll(0, 1) })
	beforeEnemy := entityRows(g, 1, engine.EntityExecutionFrame)
	g.Step(1)
	if !reflect.DeepEqual(beforeEnemy, entityRows(g, 1, engine.EntityExecutionFrame)) {
		t.Fatal("private selection leaked to opponent")
	}
	found := false
	for _, row := range entityRows(g, 0, engine.EntityExecutionFrame) {
		if row[8] == engine.ProgramDiceColor && row[9] == engine.DiceColorFire {
			found = row[3] == 2 && row[5] == 1 && row[4] == 1
		}
	}
	if !found {
		t.Fatal("own selected count, pool or remaining rerolls invisible")
	}
	replay := e.RT.Clone()
	for g.PendingDice != nil {
		a := g.GetLegalActions()[0]
		payload, err := json.Marshal(engine.InputForAction(a))
		if err != nil {
			t.Fatal(err)
		}
		rec, err := record.Parse(fmt.Sprintf("round 1:\n  actions:\n    - P0 选择重投:\n        input: %s\n", payload))
		if err != nil {
			t.Fatal(err)
		}
		r := record.Replayer{Runtime: replay, Rec: rec}
		if err := r.Step(1, 0); err != nil {
			t.Fatal(err)
		}
		g.Step(0)
	}
	if !reflect.DeepEqual(checkpointBytes(t, g), checkpointBytes(t, replay.Game)) {
		t.Fatal("record replay diverged from chosen dice selection")
	}
}
