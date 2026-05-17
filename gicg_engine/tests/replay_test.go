package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

// Round-trip test: export → parse → replay → verify state matches.
func TestReplay_RoundTrip_ChiDieVsKeShiFu(t *testing.T) {
	// First run: play a game and export
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	for step := 0; step < 500; step++ {
		if env.G.Phase == engine.PhaseGameOver {
			break
		}
		actions := env.G.GetLegalActions()
		if len(actions) == 0 {
			break
		}
		var want string
		if env.G.Turn == 0 {
			if env.Energy(0, 0) >= 3 {
				want = "回火"
			} else if env.Counter(0, 0, "蝶火_active") == 0 && env.HP(0, 0) > 5 {
				want = "蝶火"
			} else {
				want = "枪"
			}
		} else {
			if env.HandHasCard(1, "复刻") {
				want = "复刻"
			} else if env.Energy(1, 0) >= 3 {
				want = "雷暴"
			} else if env.Counter(1, 0, "刻印_雷元素附魔") == 0 {
				want = "刻印"
			} else {
				want = "剑"
			}
		}
		idx := env.FindAction(engine.ActionSkill, want)
		if idx < 0 {
			idx = env.FindAction(engine.ActionCard, want)
		}
		if idx < 0 {
			idx = env.FindAction(engine.ActionEndTurn, "")
		}
		if idx < 0 {
			idx = 0
		}
		env.Step(idx)
	}

	exported := record.Export(env.RT)
	originalWinner := env.G.Winner
	t.Logf("Original game ended: winner=%d rounds=%d", originalWinner, env.G.Round)

	// Parse the exported record
	rec, err := record.Parse(exported)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	t.Logf("Parsed %d rounds", len(rec.Rounds))

	// Second run: fresh game, replay from the record
	env2 := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	replayer := &record.Replayer{Runtime: env2.RT, Rec: rec}

	// Play each round, then verify the captured RoundStartSnap matches the record.
	// The snapshot is captured at the inter-round pause (before round_start hooks),
	// so it represents the "true beginning" of each round.
	for ri := range rec.Rounds {
		roundNum := ri + 1
		if err := replayer.PlayRound(roundNum); err != nil {
			t.Fatalf("replay round %d: %v", roundNum, err)
		}
		// Compare env2's captured snapshot for this round against the recorded state
		if rec.Rounds[ri].Start != nil && ri < len(env2.G.Log.RoundStartSnaps) {
			snap := env2.G.Log.RoundStartSnaps[ri]
			diffs := record.VerifyAgainstSnap(env2.RT, snap, rec.Rounds[ri].Start)
			if len(diffs) > 0 {
				t.Errorf("round %d start state mismatch:", roundNum)
				for _, d := range diffs {
					t.Errorf("  %s", d.String())
				}
			}
		}
		if env2.G.Phase == engine.PhaseGameOver {
			break
		}
	}

	// Final winner should match
	if env2.G.Winner != originalWinner {
		t.Errorf("winner mismatch: original=%d replay=%d", originalWinner, env2.G.Winner)
	}

	// Load test: for each recorded round, fresh-load into that round and
	// verify live state matches the recorded start state exactly.
	for ri := range rec.Rounds {
		if rec.Rounds[ri].Start == nil {
			continue
		}
		env3 := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
		if err := record.Load(env3.RT, rec, ri+1); err != nil {
			t.Fatalf("load round %d: %v", ri+1, err)
		}
		diffs := record.VerifyState(env3.RT, rec.Rounds[ri].Start)
		if len(diffs) > 0 {
			t.Errorf("load round %d: state mismatch:", ri+1)
			for _, d := range diffs {
				t.Errorf("  %s", d.String())
			}
		}
	}
}
