package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// P1 先结束回合 → 下一回合 P1 先手
func TestTurnOrder_P1EndsFirstGoesFirstNextRound(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	// Round 1 starts with P0
	if env.G.Turn != 0 {
		t.Fatalf("round 1 should start with P0, got Turn=%d", env.G.Turn)
	}

	// P0 uses skill (turn flips to P1)
	env.StepSkill("枪")
	if env.G.Turn != 1 {
		t.Fatalf("after P0 skill, turn should be P1, got %d", env.G.Turn)
	}

	// P1 ends turn first (declares end)
	idx := env.FindAction(engine.ActionEndTurn, "")
	env.Step(idx)
	// FirstEnd should now be 1
	if env.G.FirstEnd != 1 {
		t.Errorf("FirstEnd should be 1, got %d", env.G.FirstEnd)
	}

	// P0 also ends turn → round ends, game enters PhaseRoundStart (inter-round pause)
	for env.G.Phase == engine.PhaseAction {
		idx := env.FindAction(engine.ActionEndTurn, "")
		if idx < 0 {
			break
		}
		env.Step(idx)
	}
	// Trigger transition into round 2 by calling GetLegalActions (or Step)
	env.G.GetLegalActions()

	// Now in round 2
	if env.G.Round != 2 {
		t.Fatalf("expected round 2, got %d", env.G.Round)
	}
	// P1 declared end first in round 1 → P1 goes first in round 2
	if env.G.Turn != 1 {
		t.Errorf("round 2 should start with P1 (P1 ended first), got Turn=%d", env.G.Turn)
	}
}

// P0 先结束回合 → 下一回合 P0 先手
func TestTurnOrder_P0EndsFirstGoesFirstNextRound(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	// Round 1: P0 ends immediately
	idx := env.FindAction(engine.ActionEndTurn, "")
	env.Step(idx)
	if env.G.FirstEnd != 0 {
		t.Errorf("FirstEnd should be 0, got %d", env.G.FirstEnd)
	}

	// P1 ends, game enters PhaseRoundStart (inter-round pause)
	for env.G.Phase == engine.PhaseAction {
		idx := env.FindAction(engine.ActionEndTurn, "")
		if idx < 0 {
			break
		}
		env.Step(idx)
	}
	// Trigger transition into round 2
	env.G.GetLegalActions()

	if env.G.Round != 2 {
		t.Fatalf("expected round 2, got %d", env.G.Round)
	}
	if env.G.Turn != 0 {
		t.Errorf("round 2 should start with P0 (P0 ended first), got Turn=%d", env.G.Turn)
	}
}
