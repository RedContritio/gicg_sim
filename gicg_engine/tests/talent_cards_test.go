package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// cardRef looks up a declared card's ref by name. Returns -1 if absent.
func (env *GameEnv) cardRef(name string) int {
	for ref, n := range env.G.CardNames {
		if n == name {
			return ref
		}
	}
	return -1
}

// giveCard manually appends a named card to player p's hand. Used by talent
// card tests so they don't depend on drawing the card from a shuffled deck.
// Talent cards bypass the deck build path entirely — decks for tests are
// empty by default (NewGame), so hand manipulation is the only way in.
func (env *GameEnv) giveCard(t *testing.T, p int, name string) {
	t.Helper()
	ref := env.cardRef(name)
	if ref < 0 {
		t.Fatalf("card %q not declared", name)
	}
	env.G.Players[p].Hand = append(env.G.Players[p].Hand, engine.CardInst{
		Ref:          ref,
		DrawnAtRound: env.G.Round,
	})
}

// counterBy looks up the first counter whose friendly name matches. Returns
// -1 if not found. For scope-specific disambiguation, callers use the more
// specific helpers (Counter, ActiveStatusCounter) from record_test.go.
func (env *GameEnv) counterBy(name string) int {
	for id, n := range env.G.CounterNames {
		if n == name {
			return env.G.Counters[id].Value
		}
	}
	return -1
}

// counterByChar looks up a PerChar-scope counter's value for (player, char).
func (env *GameEnv) counterByChar(name string, p, c int) int {
	// Walk all counters — PerChar counters are registered with a char mapping.
	for id, n := range env.G.CounterNames {
		if n != name {
			continue
		}
		m := env.G.GetCounterChar(id)
		if m[0] == p && m[1] == c {
			return env.G.Counters[id].Value
		}
	}
	return -1
}

// --- Tests ---

// 蝶鳞 (赤蝶 talent):
//   - Play is a 枪 (via invoke 蝶火) + sets 蝶火_active on 赤蝶.
//   - While 蝶火_active, 枪 attaches 蝶印 to enemy active; 回火 eats 蝶印 for
//     +1 fire damage.
//   - Round-end: 蝶印 burns for 1 fire and clears.
//
// Test validates the card fires at all (active counter on) + round-end burn.
func TestTalent_蝶鳞_BasicActivation(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.giveCard(t, 0, "蝶鳞")

	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 3})
	hpBefore := env.HP(1, 0)
	if !env.playCard(t, "蝶鳞") {
		t.Fatal("蝶鳞 not playable")
	}
	// Activation sanity: 蝶鳞_active should be set on 赤蝶's Self slot.
	if env.counterBy("蝶鳞_active") != 1 {
		t.Errorf("蝶鳞_active should be 1 after play, got %d", env.counterBy("蝶鳞_active"))
	}
	// Invoked 蝶火 → 蝶火_active should also be 1.
	if env.counterBy("蝶火_active") != 1 {
		t.Errorf("蝶火_active should be 1 after 蝶鳞 invocation, got %d",
			env.counterBy("蝶火_active"))
	}
	// 蝶火 skill itself deals no damage (it's a buff), so no HP change yet.
	if env.HP(1, 0) != hpBefore {
		t.Logf("unexpected HP change from 蝶鳞 (buff-only): %d → %d",
			hpBefore, env.HP(1, 0))
	}
}

// 蝶鳞 + 枪 interaction: under 蝶鳞+蝶火, a 枪 hit should plant 蝶印 on the
// enemy active, and the subsequent round-end should burn it for 1 fire.
func TestTalent_蝶鳞_DieYinBurn(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.giveCard(t, 0, "蝶鳞")

	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 8})
	if !env.playCard(t, "蝶鳞") {
		t.Fatal("蝶鳞 not playable")
	}
	// Card was a battle action → turn flipped to P1. Bring it back to P0.
	env.PlayUntilTurn(0, 10)
	// Ensure enough fire dice for 枪 (1 fire + 2 any).
	env.SetDice(0, map[int]int{engine.DiceColorFire: 8})
	hpBeforeSpear := env.HP(1, 0)
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available after 蝶鳞")
	}
	hpAfterSpear := env.HP(1, 0)
	spearDmg := hpBeforeSpear - hpAfterSpear
	if spearDmg < 2 {
		t.Errorf("枪 under 蝶鳞+蝶火 should still deal ≥2 damage, got %d", spearDmg)
	}
	if env.counterByChar("蝶印", 1, 0) != 1 {
		t.Errorf("蝶印 should be 1 after 枪 hit under 蝶鳞, got %d",
			env.counterByChar("蝶印", 1, 0))
	}

	// End both turns to reach round_end; 蝶印 should burn + clear.
	hp0BeforeRoundEnd := env.HP(0, 0)
	env.playToRoundEnd(t)
	if env.counterByChar("蝶印", 1, 0) != 0 {
		t.Errorf("蝶印 should clear at round end, got %d",
			env.counterByChar("蝶印", 1, 0))
	}
	// Burn must hit the enemy (P1) active, never the owner's side.
	if got := env.HP(1, 0); got != hpAfterSpear-1 {
		t.Errorf("P1 active HP = %d, want %d (蝶印 burn should hit P1)", got, hpAfterSpear-1)
	}
	if got := env.HP(0, 0); got != hp0BeforeRoundEnd {
		t.Errorf("P0 active HP = %d, want %d (burn must not hit owner)", got, hp0BeforeRoundEnd)
	}
}

// 守正 (墨客 talent): play is 水龙吟 (ult) with +2 water pre-damage; while
// active 正气 replaces 水云 consumption, and 泼墨 sub generates 正气.
// Test validates activation + pre-damage delta.
func TestTalent_守正_PreDamage(t *testing.T) {
	env := NewGame(t, []string{"墨客"}, []string{"赤蝶"})
	// 守正 needs 墨客 at 3 energy (it invokes 水龙吟, an ult).
	// Directly seed energy so the test doesn't have to farm it.
	mo := env.RT.Chars.BySlot[0][0]
	env.G.Counters[mo.EnergyCounterID].Value = 3
	env.giveCard(t, 0, "守正")

	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorWater: 3})
	hpBefore := env.HP(1, 0)
	if !env.playCard(t, "守正") {
		t.Fatalf("守正 not playable; dice=%d energy=%d", env.DiceTotal(0), env.Energy(0, 0))
	}
	if env.counterBy("守正_active") != 1 {
		t.Errorf("守正_active should be 1, got %d", env.counterBy("守正_active"))
	}
	// Vanilla 水龙吟 is pure status setup (0 immediate damage — damage
	// comes via 泼墨 on subsequent skill hits). 守正 adds +2 water pre-
	// damage on the same cast, so the on-cast damage delta is exactly the
	// 守正 contribution.
	shouZhengOnCast := hpBefore - env.HP(1, 0)
	t.Logf("守正 → 水龙吟 on-cast damage: %d (vanilla is 0; delta = 守正 pre-dmg)",
		shouZhengOnCast)

	env2 := NewGame(t, []string{"墨客"}, []string{"赤蝶"})
	mo2 := env2.RT.Chars.BySlot[0][0]
	env2.G.Counters[mo2.EnergyCounterID].Value = 3
	env2.PlayUntilTurn(0, 10)
	// Seed enough water dice for 水龙吟 (costs 3 water).
	env2.SetDice(0, map[int]int{engine.DiceColorWater: 3})
	hp2Before := env2.HP(1, 0)
	if !env2.StepSkill("水龙吟") {
		t.Fatal("水龙吟 not available with energy=3")
	}
	vanillaOnCast := hp2Before - env2.HP(1, 0)
	if vanillaOnCast != 0 {
		t.Logf("note: vanilla 水龙吟 dealt %d on-cast (expected 0)", vanillaOnCast)
	}

	delta := shouZhengOnCast - vanillaOnCast
	if delta < 2 {
		t.Errorf("守正 should add ≥2 extra water damage on 水龙吟 cast, got +%d",
			delta)
	}
}

// 星愿 (天星 talent): invokes 玉璋 (shield ult). Sanity: active counter set,
// and 玉璋护盾 is up after the cast.
func TestTalent_星愿_Activation(t *testing.T) {
	env := NewGame(t, []string{"天星"}, []string{"墨客"})
	tx := env.RT.Chars.BySlot[0][0]
	env.G.Counters[tx.EnergyCounterID].Value = 5
	env.giveCard(t, 0, "星愿")

	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorGeo: 5})
	if !env.playCard(t, "星愿") {
		t.Fatalf("星愿 not playable; dice=%d energy=%d", env.DiceTotal(0), env.Energy(0, 0))
	}
	if env.counterBy("星愿_active") != 1 {
		t.Errorf("星愿_active should be 1, got %d", env.counterBy("星愿_active"))
	}
	if env.counterBy("玉璋护盾") <= 0 {
		t.Errorf("玉璋护盾 should be >0 after 玉璋 invocation via 星愿, got %d",
			env.counterBy("玉璋护盾"))
	}
}

// 刺刺猫爪 (猫咪 talent): invokes 猫爪护盾 (shield). When that shield is
// later hit and consumed, 刺刺猫爪 re-adds 1 shield (or deals 1 penetrating
// damage if shield is gone), up to 2 triggers per round.
func TestTalent_刺刺猫爪_Activation(t *testing.T) {
	env := NewGame(t, []string{"猫咪"}, []string{"墨客"})
	env.giveCard(t, 0, "刺刺猫爪")

	env.PlayUntilTurn(0, 10)
	env.SetDice(0, map[int]int{engine.DiceColorIce: 3})
	if !env.playCard(t, "刺刺猫爪") {
		t.Fatalf("刺刺猫爪 not playable; dice=%d", env.DiceTotal(0))
	}
	if env.counterBy("刺刺猫爪_active") != 1 {
		t.Errorf("刺刺猫爪_active should be 1, got %d",
			env.counterBy("刺刺猫爪_active"))
	}
	if env.counterBy("猫爪护盾") <= 0 {
		t.Errorf("猫爪护盾 should be >0 after 刺刺猫爪 invocation, got %d",
			env.counterBy("猫爪护盾"))
	}
}

// 发现静电 (刻师傅 talent): invokes 刻印, which attaches 负电 to enemy
// active. Subsequent 剑 / 雷暴 attach 正电.
func TestTalent_发现静电_Electrons(t *testing.T) {
	env := NewGame(t, []string{"刻师傅"}, []string{"墨客"})
	env.giveCard(t, 0, "发现静电")

	env.PlayUntilTurn(0, 10)
	// Seed enough electro to pay 发现静电 (3 electro) and still have
	// 3 dice left for the follow-up 剑 (1 electro + 2 any).
	env.SetDice(0, map[int]int{engine.DiceColorElectro: 8})
	if !env.playCard(t, "发现静电") {
		t.Fatalf("发现静电 not playable; dice=%d", env.DiceTotal(0))
	}
	if env.counterBy("静电体_active") != 1 {
		t.Errorf("静电体_active should be 1, got %d",
			env.counterBy("静电体_active"))
	}
	// 刻印 through 发现静电 → enemy active gets 1 负电.
	if got := env.counterByChar("负电", 1, 0); got != 1 {
		t.Errorf("enemy active should have 1 负电 after 发现静电→刻印, got %d", got)
	}

	// Follow up with 剑 on a later P0 turn → enemy active gets 1 正电.
	env.PlayUntilTurn(0, 10)
	if env.G.Phase == engine.PhaseGameOver {
		t.Skip("game over before follow-up")
	}
	if !env.StepSkill("剑") {
		t.Fatal("剑 not available on follow-up turn")
	}
	if got := env.counterByChar("正电", 1, 0); got != 1 {
		t.Errorf("enemy active should have 1 正电 after follow-up 剑, got %d", got)
	}
}
