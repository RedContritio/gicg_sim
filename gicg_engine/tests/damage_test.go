package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestDamage_BasicSkill(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	// Rule test: explicitly fund both players rather than depend on random rolls.
	env.SetDice(0, map[int]int{7: 8})
	env.SetDice(1, map[int]int{7: 8})
	hpBefore := env.HP(1, 0)

	// Wait for P0 turn, use 枪
	env.PlayUntilTurn(0, 10)
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available")
	}

	hpAfter := env.HP(1, 0)
	damage := hpBefore - hpAfter
	t.Logf("墨客 HP: %d → %d (damage=%d)", hpBefore, hpAfter, damage)
	if damage != 2 {
		t.Errorf("expected 2 Physical damage from 枪, got %d", damage)
	}
}

func TestDamage_DiceConsumption(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	env.PlayUntilTurn(0, 10)
	// Force a known pool so the test is deterministic regardless of roll.
	env.SetDice(0, map[int]int{
		engine.DiceColorFire: 3, // cover the 1 fire requirement of 枪
	})
	diceBefore := env.DiceTotal(0)
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available with 3 fire dice")
	}
	diceAfter := env.DiceTotal(0)

	t.Logf("dice: %d → %d", diceBefore, diceAfter)
	if diceBefore-diceAfter != 3 {
		t.Errorf("expected 3 dice cost for 枪, got %d", diceBefore-diceAfter)
	}
}

func TestDamage_MultipleSkills(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	initialHP := env.HP(1, 0)

	// Play several rounds, always use first skill
	for round := 0; round < 5; round++ {
		if env.G.Phase == engine.PhaseGameOver {
			break
		}
		env.PlayUntilTurn(0, 20)
		if env.G.Phase == engine.PhaseGameOver {
			break
		}
		// Stock enough fire dice to guarantee the skill is affordable.
		env.SetDice(0, map[int]int{engine.DiceColorFire: 8})
		env.StepSkill("枪")
	}

	finalHP := env.HP(1, 0)
	totalDamage := initialHP - finalHP
	t.Logf("Total damage after ~5 uses: %d (HP %d → %d)", totalDamage, initialHP, finalHP)
	if totalDamage < 4 {
		t.Errorf("expected significant damage, got %d", totalDamage)
	}
}

func TestDamage_ElementalReaction(t *testing.T) {
	// 赤蝶 (Fire) vs 墨客 (Water) → should trigger reactions
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.G.Log = engine.NewEventLog()

	env.PlayToEnd(200)

	var reactions int
	for _, e := range env.G.Log.Entries {
		if e.Type == "damage" {
			elem := e.Fields["element"].(int)
			raw := e.Fields["raw_value"].(int)
			final := e.Fields["final_value"].(int)
			if final > raw { // reaction bonus damage
				reactions++
			}
			_ = elem
		}
	}
	// With Fire and Water chars, we expect some elemental reactions
	t.Logf("Potential reaction-boosted hits: %d", reactions)
}

func TestDamage_GameEnds(t *testing.T) {
	cases := []struct {
		name  string
		team0 []string
		team1 []string
	}{
		{"赤蝶_vs_墨客", []string{"赤蝶"}, []string{"墨客"}},
		{"猫咪_vs_刻师傅", []string{"猫咪"}, []string{"刻师傅"}},
		{"天星_vs_赤蝶", []string{"天星"}, []string{"赤蝶"}},
		{"墨客_vs_天星", []string{"墨客"}, []string{"天星"}},
		{"刻师傅_vs_猫咪", []string{"刻师傅"}, []string{"猫咪"}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			env := NewGame(t, tc.team0, tc.team1)
			env.G.Log = engine.NewEventLog()
			env.PlayToEnd(500)

			if env.G.Phase != engine.PhaseGameOver {
				t.Errorf("game didn't end: phase=%d round=%d", env.G.Phase, env.G.Round)
			}
			if env.G.Winner < 0 {
				t.Error("no winner")
			}

			var damages, deaths int
			for _, e := range env.G.Log.Entries {
				if e.Type == "damage" {
					damages++
				}
				if e.Type == "death" {
					deaths++
				}
			}
			t.Logf("winner=%d rounds=%d damages=%d deaths=%d",
				env.G.Winner, env.G.Round, damages, deaths)

			if damages == 0 {
				t.Error("no damage events")
			}
			if deaths == 0 {
				t.Error("no death events")
			}
		})
	}
}
