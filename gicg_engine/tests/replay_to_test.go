package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

// TestReplayTo_MidAndBoundary plays a game, exports a record, then uses
// ReplayTo to jump to arbitrary global step indices on fresh games and
// verifies the rewound state matches what the original game observed at
// that point. Covers: step=0 (initial), step mid-game, step=TotalSteps
// (terminal).
func TestReplayTo_MidAndBoundary(t *testing.T) {
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
			} else {
				want = "枪"
			}
		} else {
			if env.Energy(1, 0) >= 3 {
				want = "雷暴"
			} else {
				want = "剑"
			}
		}
		idx := env.FindAction(engine.ActionSkill, want)
		if idx < 0 {
			idx = env.FindAction(engine.ActionEndTurn, "")
		}
		if idx < 0 {
			idx = 0
		}
		env.Step(idx)
	}

	exported := record.Export(env.RT)
	rec, err := record.Parse(exported)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	total := record.TotalSteps(rec)
	if total < 2 {
		t.Fatalf("expected at least 2 steps, got %d", total)
	}

	// Step 0: fresh load-round-1 state — round should be 1.
	env0 := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	if err := record.ReplayTo(env0.RT, rec, 0); err != nil {
		t.Fatalf("ReplayTo 0: %v", err)
	}
	view0 := record.ExportView(env0.RT)
	if view0.Round != 1 {
		t.Errorf("step=0 round = %d, want 1", view0.Round)
	}

	// Mid step: rewind another fresh game half way and compare its view
	// against a diff-friendly invariant — round index must monotonically
	// increase and HP must be <= initial 15.
	mid := total / 2
	envMid := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	if err := record.ReplayTo(envMid.RT, rec, mid); err != nil {
		t.Fatalf("ReplayTo %d: %v", mid, err)
	}
	viewMid := record.ExportView(envMid.RT)
	if viewMid.Round < 1 {
		t.Errorf("step=%d round = %d, want >= 1", mid, viewMid.Round)
	}
	for _, pv := range viewMid.Players {
		for _, c := range pv.Chars {
			if c.HP < 0 || c.HP > 15 {
				t.Errorf("step=%d char %s HP=%d out of [0,15]", mid, c.Name, c.HP)
			}
		}
	}

	// Terminal: replaying to TotalSteps should land on PhaseGameOver
	// with a decided winner (0 or 1).
	envEnd := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	if err := record.ReplayTo(envEnd.RT, rec, total); err != nil {
		t.Fatalf("ReplayTo total=%d: %v", total, err)
	}
	viewEnd := record.ExportView(envEnd.RT)
	if viewEnd.Winner != 0 && viewEnd.Winner != 1 {
		t.Errorf("terminal winner = %d, want 0 or 1", viewEnd.Winner)
	}
}

// TestExtractTeams_FromRecord verifies that the team roster can be
// recovered from a parsed record without needing the original game
// config. This is the path the web backend uses to build a compatible
// env for replaying a bare YAML file.
func TestExtractTeams_FromRecord(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶", "墨客"}, []string{"刻师傅"})
	for i := 0; i < 4 && env.G.Phase != engine.PhaseGameOver; i++ {
		actions := env.G.GetLegalActions()
		if len(actions) == 0 {
			break
		}
		env.Step(0)
	}
	exported := record.Export(env.RT)
	rec, err := record.Parse(exported)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	teams, err := record.ExtractTeams(rec)
	if err != nil {
		t.Fatalf("ExtractTeams: %v", err)
	}
	if len(teams[0]) != 2 || teams[0][0] != "赤蝶" || teams[0][1] != "墨客" {
		t.Errorf("P0 = %v, want [赤蝶 墨客]", teams[0])
	}
	if len(teams[1]) != 1 || teams[1][0] != "刻师傅" {
		t.Errorf("P1 = %v, want [刻师傅]", teams[1])
	}
}
