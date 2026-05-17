package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestMirrorMatchSkillsWork is a regression test for the per-name CharEntry
// bug: in mirror match (both teams have the same character), skills must be
// attached to BOTH players' chars, not just the second-bound one.
func TestMirrorMatchSkillsWork(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})

	e0 := env.RT.Chars.BySlot[0][0]
	e1 := env.RT.Chars.BySlot[1][0]
	if len(e0.SkillIDs) == 0 {
		t.Errorf("P0 char has no SkillIDs (regression: per-name bug)")
	}
	if len(e1.SkillIDs) == 0 {
		t.Errorf("P1 char has no SkillIDs")
	}
	t.Logf("e0.SkillIDs=%v  e1.SkillIDs=%v", e0.SkillIDs, e1.SkillIDs)

	// Engine-side: each player's CharInfo should have skills too.
	if len(env.G.Players[0].Chars[0].Skills) == 0 {
		t.Errorf("P0 engine char has no skills")
	}
	if len(env.G.Players[1].Chars[0].Skills) == 0 {
		t.Errorf("P1 engine char has no skills")
	}

	// P0 should see skill actions in legal actions.
	if !env.PlayUntilTurn(0, 10) {
		t.Fatal("could not reach P0 turn")
	}
	skillFound := false
	for _, a := range env.G.GetLegalActions() {
		if a.Kind == engine.ActionSkill {
			skillFound = true
			break
		}
	}
	if !skillFound {
		t.Errorf("P0 has no skill in legal actions on its turn")
	}
}

// TestMirrorMatchBuff_NoDoubleFire is the regression test for
// issue #152. Before the fix, loading a buff DSL file per-binding
// meant a mirror matchup (赤蝶 vs 赤蝶) registered each hook twice:
// once with OwnerPlayer=0, once with OwnerPlayer=1. Every event
// fired both copies, and whichever side had its Self-scope buff
// counter active would contribute its effect — so if both sides
// opened 蝶火, P0's 枪 damage got the +2 buff TWICE, producing
// 6 fire damage instead of the correct 4.
//
// Fix: DSL files capture their loading owner via owner_player() /
// owner_char() and filter ctx.actor_player / ctx.actor_char at
// every actor-centric hook. Engine fires all hooks; DSL authors
// own the "this event is mine" check.
//
// Test shape:
//  1. Both赤蝶 open 蝶火 (so both buff counters active)
//  2. P0 出枪
//  3. Expected damage: 4 (Physical→Fire + 2 base + 2 蝶火 boost)
//     Bug behavior: 6 (boost applied twice)
func TestMirrorMatchBuff_NoDoubleFire(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})

	// Both sides open 蝶火. Cost 3 fire.
	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 3})
	if !env.StepSkill("蝶火") {
		t.Fatal("P0 蝶火 not available")
	}
	env.PlayUntilTurn(1, 10)
	env.SetDice(1, map[int]int{engine.DiceColorFire: 3})
	if !env.StepSkill("蝶火") {
		t.Fatal("P1 蝶火 not available")
	}

	// P0 出枪打 P1
	env.PlayUntilTurn(0, 20)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 3})
	hpBefore := env.HP(1, 0)
	if !env.StepSkill("枪") {
		t.Fatal("P0 枪 not available")
	}
	hpAfter := env.HP(1, 0)
	damage := hpBefore - hpAfter

	// Expected: 2 base Physical, 蝶火 boosts P0's own attack to
	// Fire +2 → 4 fire damage. (P1's 蝶火 buff should NOT apply
	// to P0's damage after the fix — that's the whole point.)
	if damage != 4 {
		t.Errorf(
			"mirror-match bug #152: P0 枪 under own 蝶火 should deal "+
				"4 damage, got %d. Value %d means P1's 蝶火 buff "+
				"also fired on P0's damage event (double-boost).",
			damage, damage,
		)
	}
}

// TestMirrorMatch_BasicAttack_NoDouble is a lightweight per-char
// regression: mirror match (X vs X), P0 出普攻, 受到 2 物理伤害
// (not 4). Covers the simplest case — the on_skill_use hook that
// deal_damage's — across every shipped character, catching any
// char file whose 普攻 on_skill_use was missed in the #152
// migration. See TestMirrorMatchBuff_NoDoubleFire for the full
// buff-path test.
//
// Dice cost for 普攻 is always { <element> = 1, any = 2 } → total 3
// dice. The test pre-stocks a 3-element pool matching the char's
// element so the attack affords.
// TestMirrorMatch_Talent_AvailableBothSides verifies the B-plan
// shared-load talent path: a talent card (蝶鳞, requires_char=赤蝶) is
// loaded once globally but addressable from BOTH sides of a mirror
// match. The filter drops only "k==0" (nobody has the char), so mirror
// k=2 keeps the card. Internals (SelfSlotProxy + LazyCharProxy +
// LazySkillRef) resolve to the correct slot at hook-fire time per
// ctx.actor_player.
//
// Test shape:
//  1. Mirror 赤蝶 vs 赤蝶. Give 蝶鳞 to BOTH sides.
//  2. P0 plays 蝶鳞: P0's 蝶鳞_active + 蝶火_active go to 1, P1's stay 0.
//  3. P1 plays 蝶鳞: P1's counters go to 1, both sides now active
//     independently.
//  4. P0 出枪 under own 蝶火: deal 4 fire (Physical→Fire +2). P1's
//     蝶火_active does NOT boost P0 (would show 6 on double-boost bug).
func TestMirrorMatch_Talent_AvailableBothSides(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})
	env.giveCard(t, 0, "蝶鳞")
	env.giveCard(t, 1, "蝶鳞")

	// P0 plays 蝶鳞
	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 3})
	if !env.playCard(t, "蝶鳞") {
		t.Fatal("P0 蝶鳞 not playable")
	}

	p0_die_active_after_p0 := env.counterByChar("蝶鳞_active", 0, 0)
	p1_die_active_after_p0 := env.counterByChar("蝶鳞_active", 1, 0)
	if p0_die_active_after_p0 != 1 {
		t.Errorf("P0 蝶鳞_active should be 1 after P0 play, got %d", p0_die_active_after_p0)
	}
	if p1_die_active_after_p0 != 0 {
		t.Errorf("P1 蝶鳞_active should still be 0 before P1 plays, got %d", p1_die_active_after_p0)
	}

	// P1 plays 蝶鳞
	env.PlayUntilTurn(1, 10)
	env.SetDice(1, map[int]int{engine.DiceColorFire: 3})
	if !env.playCard(t, "蝶鳞") {
		t.Fatal("P1 蝶鳞 not playable")
	}
	if env.counterByChar("蝶鳞_active", 1, 0) != 1 {
		t.Errorf("P1 蝶鳞_active should be 1 after P1 play")
	}
	if env.counterByChar("蝶鳞_active", 0, 0) != 1 {
		t.Errorf("P0 蝶鳞_active should remain 1 (was set by P0 earlier)")
	}

	// P0 出枪: expect 4 fire damage, not 6 (would be 6 if P1's 蝶火 also
	// boosted P0's damage — the talent-mirror double-fire bug).
	env.PlayUntilTurn(0, 20)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 3})
	hpBefore := env.HP(1, 0)
	if !env.StepSkill("枪") {
		t.Fatal("P0 枪 not available")
	}
	hpAfter := env.HP(1, 0)
	damage := hpBefore - hpAfter
	if damage != 4 {
		t.Errorf("P0 枪 under own 蝶鳞/蝶火 should deal 4 fire damage, got %d "+
			"(6 would mean P1's 蝶火_active also boosted P0's damage — "+
			"shared-load talent SelfSlotProxy isolation broken)", damage)
	}
}

func TestMirrorMatch_BasicAttack_NoDouble(t *testing.T) {
	cases := []struct {
		char       string
		skill      string
		element    int // dice color to stock for this char
		expectedHP int // expected damage dealt
	}{
		{"赤蝶", "枪", engine.DiceColorFire, 2},
		{"墨客", "剑", engine.DiceColorWater, 2},
		{"猫咪", "箭", engine.DiceColorIce, 2},
		{"刻师傅", "剑", engine.DiceColorElectro, 2},
		{"天星", "枪", engine.DiceColorGeo, 2},
	}
	for _, tc := range cases {
		t.Run(tc.char, func(t *testing.T) {
			env := NewGame(t, []string{tc.char}, []string{tc.char})
			env.PlayUntilTurn(0, 10)
			env.SetDice(0, map[int]int{tc.element: 3})
			hpBefore := env.HP(1, 0)
			if !env.StepSkill(tc.skill) {
				t.Fatalf("%s mirror: P0 %s not available", tc.char, tc.skill)
			}
			hpAfter := env.HP(1, 0)
			damage := hpBefore - hpAfter
			if damage != tc.expectedHP {
				t.Errorf(
					"%s mirror: expected %d damage from %s, got %d "+
						"(double-fire bug #152 would show 4)",
					tc.char, tc.expectedHP, tc.skill, damage,
				)
			}
		})
	}
}
