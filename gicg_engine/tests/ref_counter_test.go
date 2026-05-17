package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestRefCounter_铁剑_RepeatSkillDiscount verifies the 铁剑 weapon
// card's "same skill twice = -1 cost" effect fires correctly now
// that its last_skill counter uses ref_kind = RefKind.Skill (so
// identity comparison via pointer works).
//
// Flow:
//  1. Equip 铁剑 on 墨客 (sword wielder).
//  2. Set dice pool high for water + any.
//  3. Use 剑 once — establishes last_skill marker, no discount.
//  4. Use 剑 again — discount applies; cost should be 2 dice instead
//     of 3, and last_skill marker should be cleared.
func TestRefCounter_铁剑_RepeatSkillDiscount(t *testing.T) {
	env := NewGame(t, []string{"墨客"}, []string{"赤蝶"})

	env.giveCard(t, 0, "铁剑")

	env.PlayUntilTurn(0, 10)
	// Seed enough water for 2 dice costs of 剑 (1 water + 2 any each).
	env.SetDice(0, map[int]int{engine.DiceColorWater: 16})

	// Play 铁剑 → equips on 墨客 (c0). This is not a battle action so
	// P0 retains the turn.
	if !env.playCard(t, "铁剑") {
		t.Fatalf("铁剑 not playable")
	}

	env.PlayUntilTurn(0, 10)
	dice1 := env.DiceTotal(0)

	// First 剑 use — no discount yet (last_skill was nil, no match).
	if !env.StepSkill("剑") {
		t.Fatal("剑 not available (first use)")
	}
	spent1 := dice1 - env.DiceTotal(0)
	if spent1 != 3 {
		t.Errorf("first 剑 use: spent %d dice, want 3 (no discount)", spent1)
	}

	// Bring turn back to P0.
	env.PlayUntilTurn(0, 10)
	dice2 := env.DiceTotal(0)

	// Second 剑 use — last_skill matches, discount applies.
	if !env.StepSkill("剑") {
		t.Fatal("剑 not available (second use)")
	}
	spent2 := dice2 - env.DiceTotal(0)
	if spent2 != 2 {
		t.Errorf("second 剑 use: spent %d dice, want 2 (-1 via 铁剑 repeat-skill discount)", spent2)
	}
}

// TestRefCounter_NilSentinel verifies that a ref-kind counter
// returns nil when the stored sentinel value is the default
// uninitialized state.
func TestRefCounter_NilSentinel(t *testing.T) {
	// 铁剑_last_skill is PerChar, ref_kind = Skill. On a fresh game,
	// it's nil. We check via the engine counter value: should be -1
	// (the sentinel).
	env := NewGame(t, []string{"墨客"}, []string{"赤蝶"})

	// Find the 铁剑_last_skill counter for P0 C0.
	for id, name := range env.G.CounterNames {
		if name != "铁剑_last_skill" {
			continue
		}
		m := env.G.GetCounterChar(id)
		if m[0] != 0 || m[1] != 0 {
			continue
		}
		if env.G.Counters[id].Value != -1 {
			t.Errorf("fresh ref counter: raw value = %d, want -1 (nil sentinel)",
				env.G.Counters[id].Value)
		}
		return
	}
	t.Fatal("铁剑_last_skill counter for P0 C0 not found")
}
