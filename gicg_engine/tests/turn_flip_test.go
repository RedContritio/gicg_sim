package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestTurnFlip_DeclaredEndIsSkipped is a regression for the turn-order bug
// where, after one player declared end-of-round, BattleAction turn flips by
// the active player would still hand control back to the declared-end player
// for one futile EndTurn poll, costing the active player tempo. The fix is
// in action.go's flipTurn helper.
//
// Setup: P0 declares end immediately. P1 then uses a skill (BattleAction).
// Expected: turn stays on P1 — P0 is locked out for the rest of the round.
func TestTurnFlip_DeclaredEndIsSkipped(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	if !env.PlayUntilTurn(0, 10) {
		t.Fatal("could not reach P0 action turn")
	}

	// P0 EndTurn first.
	endIdx := env.FindAction(engine.ActionEndTurn, "")
	if endIdx < 0 {
		t.Fatal("P0 cannot find EndTurn")
	}
	env.Step(endIdx)

	if !env.G.Players[0].DeclaredEnd {
		t.Fatal("after P0 EndTurn, P0.DeclaredEnd should be true")
	}
	if env.G.Turn != 1 {
		t.Fatalf("after P0 EndTurn, expected Turn=1, got %d", env.G.Turn)
	}

	// P1 takes a skill (BattleAction). The bug was: after this, Turn would
	// flip back to P0 even though P0 already DeclaredEnd, forcing P0 to
	// EndTurn again. The fix keeps Turn on P1 so they retain exclusive
	// control until they themselves EndTurn.
	if !env.StepSkill("普通攻击") && !env.StepSkill("枪") {
		// 墨客's basic / 赤蝶's basic — try whichever; either is BattleAction
		var skillName string
		for _, a := range env.G.GetLegalActions() {
			if a.Kind == engine.ActionSkill {
				skillName = env.G.SkillNames[a.Index]
				break
			}
		}
		if skillName == "" {
			t.Fatal("P1 has no skill action")
		}
		env.StepSkill(skillName)
	}

	if env.G.Phase != engine.PhaseAction {
		t.Fatalf("game should still be in PhaseAction (P1 hasn't ended yet); phase=%v",
			env.G.Phase)
	}
	if env.G.Turn != 1 {
		t.Errorf("after P1 BattleAction with P0 already DeclaredEnd, "+
			"Turn should remain 1, got %d", env.G.Turn)
	}
	if env.G.Players[0].DeclaredEnd != true {
		t.Errorf("P0.DeclaredEnd should still be true")
	}
	if env.G.Players[1].DeclaredEnd != false {
		t.Errorf("P1.DeclaredEnd should still be false")
	}
}

// TestTurnFlip_NormalAlternationWhenBothActive checks the fix doesn't break
// the normal alternating turn pattern when neither player has DeclaredEnd.
func TestTurnFlip_NormalAlternationWhenBothActive(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	// Rule test: explicitly fund both players rather than depend on random rolls.
	env.SetDice(0, map[int]int{7: 8})
	env.SetDice(1, map[int]int{7: 8})
	if !env.PlayUntilTurn(0, 10) {
		t.Fatal("could not reach P0 action turn")
	}
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available")
	}
	if env.G.Turn != 1 {
		t.Errorf("after P0 skill (neither DeclaredEnd), Turn should flip to 1, got %d",
			env.G.Turn)
	}
}
