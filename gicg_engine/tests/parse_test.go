package tests

import (
	"os"
	"path/filepath"
	"testing"

	"gicg_mono/gicg_engine/record"
)

func TestParse_ExistingReplay(t *testing.T) {
	path := filepath.Join(replayDir, "赤蝶_vs_刻师傅.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Skip("no existing replay")
	}

	rec, err := record.Parse(string(data))
	if err != nil {
		t.Fatalf("parse: %v", err)
	}

	t.Logf("Rounds: %d, Winner: %d", len(rec.Rounds), rec.Winner)

	for _, r := range rec.Rounds {
		t.Logf("=== Round %d ===", r.Number)
		if r.Start != nil {
			t.Logf("  state.P0 counters=%v hand=%v deck=%v chars=%d",
				r.Start.P0.Counters, r.Start.P0.Hand, r.Start.P0.Deck, len(r.Start.P0.Chars))
			for _, c := range r.Start.P0.Chars {
				t.Logf("    P0 %s: %v", c.Name, c.Counters)
			}
		}
		for j, a := range r.Actions {
			t.Logf("  [%d] P%d %s %s", j, a.Player, a.Kind, a.Name)
		}
	}

	// Sanity checks
	if len(rec.Rounds) == 0 {
		t.Fatal("no rounds parsed")
	}
	if rec.Rounds[0].Start == nil {
		t.Fatal("round 1 has no state")
	}
	// Round 1 state should be the initial state
	if len(rec.Rounds[0].Start.P0.Chars) == 0 {
		t.Error("round 1 state has no P0 chars")
	}
	// Winner balance is gameplay-dependent (not a parse concern). Just
	// validate it's a legitimate value.
	if rec.Winner < 0 || rec.Winner > 1 {
		t.Errorf("invalid winner: %d", rec.Winner)
	}
}
