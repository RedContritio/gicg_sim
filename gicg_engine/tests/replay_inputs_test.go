package tests

import (
	"reflect"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

func TestReplayExactInputsAcrossReceiverSeeds(t *testing.T) {
	for _, seed := range []int64{7, 42, 1337} {
		source := newGame(t, []string{"赤蝶"}, []string{"墨客"}, seed, true)
		initial, err := record.Parse(record.Export(source.RT))
		if err != nil {
			t.Fatal(err)
		}
		initialSteps := record.TotalSteps(initial)
		var inputs []engine.ActionInput
		// Exercise non-default payments and tuning without crossing a round
		// boundary (cached later-round state has separate completeness tests).
		for step := 0; step < 16; step++ {
			if source.G.Phase == engine.PhaseGameOver || source.G.Phase == engine.PhaseRoundStart {
				break
			}
			actions := source.G.GetLegalActions()
			if len(actions) == 0 {
				break
			}
			idx := -1
			for i := len(actions) - 1; i >= 0; i-- {
				if actions[i].Kind != engine.ActionEndTurn {
					idx = i
					break
				}
			}
			if idx < 0 {
				break
			}
			inputs = append(inputs, engine.InputForAction(actions[idx]))
			source.G.Step(idx)
		}
		if len(inputs) == 0 {
			t.Fatal("fixture exercised no actions")
		}
		rec, err := record.Parse(record.Export(source.RT))
		if err != nil {
			t.Fatal(err)
		}
		if record.TotalSteps(rec) != initialSteps+len(inputs) {
			t.Fatalf("seed %d: lost actions", seed)
		}
		for i, a := range rec.Rounds[0].Actions[initialSteps:] {
			if a.Input == nil || *a.Input != inputs[i] {
				t.Fatalf("seed %d action %d lost exact input", seed, i)
			}
		}
		receiver := newGame(t, []string{"赤蝶"}, []string{"墨客"}, 999, true)
		if err := record.ReplayTo(receiver.RT, rec, record.TotalSteps(rec)); err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
		if !reflect.DeepEqual(source.G.Counters, receiver.G.Counters) {
			for i, c := range source.G.Counters {
				if c != receiver.G.Counters[i] {
					t.Errorf("seed %d counter %d %s: source=%+v replay=%+v", seed, i, source.G.CounterNames[i], c, receiver.G.Counters[i])
				}
			}
			t.FailNow()
		}
		for pi := range source.G.Players {
			if source.G.DicePaid[pi] != receiver.G.DicePaid[pi] {
				t.Fatalf("seed %d: P%d dice diverged", seed, pi)
			}
		}
	}
}
