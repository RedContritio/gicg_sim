package tests

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

func checkpointBytes(t *testing.T, g *engine.Game) []byte {
	t.Helper()
	b, err := g.ExportCheckpoint()
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestCheckpointPreservesAllStateAndRandomStreams(t *testing.T) {
	source := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	receiver := newGame(t, []string{"赤蝶"}, []string{"墨客"}, 987, true)
	ref := source.G.Players[0].Hand[0].Ref
	source.G.Players[0].Supports = []engine.SupportInst{{Ref: ref, ActivatedAt: 1}}
	source.G.Players[0].Chars[0].SpecialtyCardRef = ref
	source.G.Players[0].Discard = []engine.CardInst{{Ref: ref, DrawnAtRound: 1}}
	source.G.Preparing[0] = source.G.Players[0].Chars[0].Skills[0]
	for i := 0; i < 17; i++ {
		source.G.Rng.Intn(7)
		source.G.DeckRngs[0].Uint64()
		source.G.DeckRngs[1].Intn(19)
	}
	state := checkpointBytes(t, source.G)
	if err := receiver.G.RestoreCheckpoint(state); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(state, checkpointBytes(t, receiver.G)) {
		t.Fatal("checkpoint state was not restored exactly")
	}
	for i := 0; i < 100; i++ {
		if source.G.Rng.Intn(111) != receiver.G.Rng.Intn(111) {
			t.Fatal("game RNG diverged")
		}
		for pi := range source.G.DeckRngs {
			if source.G.DeckRngs[pi].Uint64() != receiver.G.DeckRngs[pi].Uint64() {
				t.Fatal("deck RNG diverged")
			}
		}
	}
	// Re-serializing after draws catches wrappers accidentally bound to a
	// temporary RNG's source rather than the deserialized object's source.
	if !bytes.Equal(checkpointBytes(t, source.G), checkpointBytes(t, receiver.G)) {
		t.Fatal("serialized RNG did not track draws")
	}
}

func TestCheckpointRejectsCorruptionWithoutMutation(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	before := checkpointBytes(t, env.G)
	for _, edit := range []func(map[string]any){
		func(c map[string]any) { c["Version"] = 99 },
		func(c map[string]any) { c["RandomProtocol"] = "legacy" },
		func(c map[string]any) { c["LayoutHash"] = "different" },
		func(c map[string]any) { c["RulesDigest"] = "different-rules" },
		func(c map[string]any) { c["State"].(map[string]any)["Rng"] = "broken" },
		func(c map[string]any) { c["State"].(map[string]any)["Turn"] = 7 },
		func(c map[string]any) { delete(c["State"].(map[string]any), "DicePaid") },
		func(c map[string]any) { c["State"].(map[string]any)["DicePaid"] = [][]int{{1}, {2}} },
		func(c map[string]any) {
			c["State"].(map[string]any)["Counters"].([]any)[0].(map[string]any)["Max"] = -3
		},
	} {
		var c map[string]any
		if err := json.Unmarshal(before, &c); err != nil {
			t.Fatal(err)
		}
		edit(c)
		bad, _ := json.Marshal(c)
		if err := env.G.RestoreCheckpoint(bad); err == nil {
			t.Fatal("corrupt checkpoint accepted")
		}
		if !bytes.Equal(before, checkpointBytes(t, env.G)) {
			t.Fatal("failed import mutated receiver: " + checkpointDiff(before, checkpointBytes(t, env.G)))
		}
	}
}

func TestRecordRejectsCheckpointProjectionMismatch(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	before := checkpointBytes(t, env.G)
	r, err := record.Parse(record.Export(env.RT))
	if err != nil {
		t.Fatal(err)
	}
	r.Rounds[0].Start.P0.Chars[0].Counters["生命"]++
	if err := record.Load(env.RT, r, 1); err == nil {
		t.Fatal("contradictory checkpoint/projection accepted")
	}
	if !bytes.Equal(before, checkpointBytes(t, env.G)) {
		t.Fatal("rejected record changed game")
	}
}

func TestReplayToFallsBackForIncompatibleCheckpoint(t *testing.T) {
	source := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	r, err := record.Parse(record.Export(source.RT))
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Rounds) == 0 || r.Rounds[0].Start.Checkpoint == nil {
		t.Fatal("fixture has no checkpoint")
	}
	var c map[string]any
	if err := json.Unmarshal(r.Rounds[0].Start.Checkpoint, &c); err != nil {
		t.Fatal(err)
	}
	c["LayoutHash"] = "different"
	r.Rounds[0].Start.Checkpoint, err = json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}

	receiver := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	receiver.G.Winner = 1
	receiver.G.Phase = engine.PhaseGameOver
	receiver.G.Round = 9
	receiver.G.Players[0].Supports = []engine.SupportInst{{Ref: 1, ActivatedAt: 1}}
	receiver.G.RewardAccum[0].DamageDealt = 7
	receiver.G.DicePaid[0][0] = 3
	if err := record.Load(receiver.RT, r, 1); !errors.Is(err, engine.ErrCheckpointIncompatible) {
		t.Fatalf("strict load error = %v, want ErrCheckpointIncompatible", err)
	}
	if err := record.ReplayTo(receiver.RT, r, 0); err != nil {
		t.Fatalf("replay fallback failed: %v", err)
	}
	if receiver.G.Winner != -1 || receiver.G.Round != 1 || receiver.G.Phase == engine.PhaseGameOver {
		t.Fatalf("fallback retained terminal state: winner=%d round=%d phase=%d", receiver.G.Winner, receiver.G.Round, receiver.G.Phase)
	}
	if len(receiver.G.Players[0].Supports) != 0 || receiver.G.RewardAccum[0].DamageDealt != 0 || receiver.G.DicePaid[0][0] != 0 {
		t.Fatal("fallback retained stale dynamic state")
	}
}

func TestReplayToRejectsActionsAfterGameOver(t *testing.T) {
	source := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	rng := engine.NewRandom(123)
	for source.G.Phase != engine.PhaseGameOver && source.G.Round < 12 {
		actions := source.G.GetLegalActions()
		if len(actions) == 0 {
			t.Fatal("live game has no legal action")
		}
		source.G.Step(rng.Intn(len(actions)))
	}
	if source.G.Phase != engine.PhaseGameOver {
		t.Fatal("fixture did not reach game over")
	}
	r, err := record.Parse(record.Export(source.RT))
	if err != nil {
		t.Fatal(err)
	}
	last := &r.Rounds[len(r.Rounds)-1]
	last.Actions = append(last.Actions, record.Action{Player: 0, Kind: record.ActEndTurn, TargetPlayer: -1})

	receiver := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	err = record.ReplayTo(receiver.RT, r, record.TotalSteps(r))
	if err == nil || !strings.Contains(err.Error(), "game over before") {
		t.Fatalf("ReplayTo error = %v, want game-over truncation error", err)
	}
}

func TestRecordLoadFailureIsAtomic(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	before := checkpointBytes(t, env.G)
	r, err := record.Parse(record.Export(env.RT))
	if err != nil {
		t.Fatal(err)
	}
	// Exercise legacy load after it has already overwritten P0's zones.
	r.Rounds[0].Start.Checkpoint = nil
	r.Rounds[0].Start.P1.Hand = []string{"missing-card"}
	if err := record.Load(env.RT, r, 1); err == nil {
		t.Fatal("invalid legacy state accepted")
	}
	if !bytes.Equal(before, checkpointBytes(t, env.G)) {
		t.Fatal("failed record load mutated receiver")
	}
}

func TestReplayEveryPrefixAcrossRounds(t *testing.T) {
	source := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	rng := engine.NewRandom(123)
	expected := map[int][]byte{}
	steps := 0
	for steps < 300 && source.G.Phase != engine.PhaseGameOver {
		actions := source.G.GetLegalActions()
		if len(actions) == 0 {
			t.Fatal("live game has no legal action")
		}
		source.G.Step(rng.Intn(len(actions)))
		steps++
		// ReplayTo deliberately advances a round pause before presenting it.
		if source.G.Phase != engine.PhaseRoundStart {
			expected[steps] = checkpointBytes(t, source.G)
		}
	}
	if source.G.Round < 2 || source.G.Phase != engine.PhaseGameOver {
		t.Fatal("fixture did not exercise a complete multi-round game")
	}
	r, err := record.Parse(record.Export(source.RT))
	if err != nil {
		t.Fatal(err)
	}
	if record.TotalSteps(r) != steps {
		t.Fatalf("lost decisions: %d vs %d", record.TotalSteps(r), steps)
	}
	receiver := newGame(t, []string{"赤蝶"}, []string{"墨客"}, 777, true)
	// Reverse order verifies that loading a prior round also clears later
	// gameplay state, including Winner and terminal phase.
	for step := steps; step > 0; step-- {
		want, ok := expected[step]
		if !ok {
			continue
		}
		if err := record.ReplayTo(receiver.RT, r, step); err != nil {
			t.Fatalf("step %d: %v", step, err)
		}
		if !bytes.Equal(want, checkpointBytes(t, receiver.G)) {
			t.Fatalf("step %d: complete replay state diverged: %s", step, checkpointDiff(want, checkpointBytes(t, receiver.G)))
		}
	}
}

func checkpointDiff(a, b []byte) string {
	for i := 0; i < len(a) && i < len(b); i++ {
		if a[i] != b[i] {
			return fmt.Sprintf("at %d: want %s got %s", i, a[max(0, i-30):min(len(a), i+150)], b[max(0, i-30):min(len(b), i+150)])
		}
	}
	return fmt.Sprintf("lengths %d/%d", len(a), len(b))
}
