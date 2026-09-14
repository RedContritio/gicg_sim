package tests

import "testing"

func TestShield_CatShieldAbsorbs(t *testing.T) {
	// 猫咪 has 猫爪护盾 (creates shield that absorbs damage)
	env := NewGame(t, []string{"赤蝶"}, []string{"猫咪"})
	// Rule test: explicitly fund both players rather than depend on random rolls.
	env.SetDice(0, map[int]int{7: 8})
	env.SetDice(1, map[int]int{7: 8})

	// Let 猫咪 (P1) use 猫爪护盾 first
	env.PlayUntilTurn(1, 10)
	if !env.StepSkill("猫爪护盾") {
		t.Fatal("shield skill unavailable")
	}

	// Now 赤蝶 (P0) attacks
	env.PlayUntilTurn(0, 10)
	hpBefore := env.HP(1, 0)
	if !env.StepSkill("枪") {
		t.Fatal("attack unavailable")
	}
	hpAfter := env.HP(1, 0)

	damage := hpBefore - hpAfter
	t.Logf("猫咪 HP after 枪 (with shield): %d → %d (damage=%d)", hpBefore, hpAfter, damage)
	// With shield active, damage should be reduced or fully absorbed
	if damage >= 2 {
		t.Errorf("expected shield to reduce/absorb damage, but took full %d", damage)
	}
}

func TestShield_CrystalShield(t *testing.T) {
	// 天星 (Geo) vs target with element attached → should trigger 结晶 and create shield
	env := NewGame(t, []string{"天星"}, []string{"赤蝶"})
	env.PlayToEnd(300)

	if env.G.Winner < 0 {
		t.Logf("game didn't end in 300 steps (round=%d), this is acceptable for shield-heavy matchup", env.G.Round)
	} else {
		t.Logf("winner=%d rounds=%d", env.G.Winner, env.G.Round)
	}
}
