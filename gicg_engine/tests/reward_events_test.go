package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestRewardEvents_InitialZero asserts a freshly-constructed game has
// all 14 reward counters at zero for both players — no bleeding from
// hooks fired during round-start / select-active.
func TestRewardEvents_InitialZero(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	for p := 0; p < 2; p++ {
		r := env.G.RewardAccum[p]
		if r != (engine.RewardEvents{}) {
			t.Errorf("P%d RewardAccum not zero at init: %+v", p, r)
		}
	}
}

// TestRewardEvents_DamageIncrements: firing a basic skill against a
// plain target should bump both sides' damage accumulators by the
// actual HP delta.
func TestRewardEvents_DamageIncrements(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.PlayUntilTurn(0, 10)
	hpBefore := env.HP(1, 0)
	env.SetDice(0, map[int]int{engine.DiceColorFire: 3})
	if !env.StepSkill("枪") {
		t.Fatal("枪 not available")
	}
	hpAfter := env.HP(1, 0)
	expected := hpBefore - hpAfter
	if expected <= 0 {
		t.Fatalf("no damage landed (hp %d → %d)", hpBefore, hpAfter)
	}
	if got := env.G.RewardAccum[0].DamageDealt; got != expected {
		t.Errorf("P0.DamageDealt = %d, want %d", got, expected)
	}
	if got := env.G.RewardAccum[1].DamageReceived; got != expected {
		t.Errorf("P1.DamageReceived = %d, want %d", got, expected)
	}
}

// TestRewardEvents_ResetDynamicStateZeroes: ResetDynamicState must
// clear RewardAccum so the next episode starts from a clean slate.
func TestRewardEvents_ResetDynamicStateZeroes(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	// Force a non-zero accumulator by hand, so the test exercises the
	// reset path regardless of whether normal play landed damage.
	env.G.RewardAccum[0].DamageDealt = 99
	env.G.RewardAccum[1].Kills = 3
	env.G.RewardAccum[1].TotalKills = 3

	env.G.ResetDynamicState(42)
	for p := 0; p < 2; p++ {
		if env.G.RewardAccum[p] != (engine.RewardEvents{}) {
			t.Errorf("P%d RewardAccum not zero after ResetDynamicState: %+v", p, env.G.RewardAccum[p])
		}
	}
}

// TestRewardEvents_SnapshotRestoreSurvives: RestoreFrom must carry the
// snapshot's RewardAccum back — critical for GreedyPlayer depth>=2
// which brackets a simulated action with snapshot/restore and reads
// the delta.
func TestRewardEvents_SnapshotRestoreSurvives(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.G.RewardAccum[0].DamageDealt = 17
	env.G.RewardAccum[1].ShieldAbsorbed = 5

	snap := env.G.DeepCopy()

	// Mutate original; the snap must still hold pre-mutation values.
	env.G.RewardAccum[0].DamageDealt = 100
	env.G.RewardAccum[1].ShieldAbsorbed = 0

	env.G.RestoreFrom(snap)
	if got := env.G.RewardAccum[0].DamageDealt; got != 17 {
		t.Errorf("after Restore, P0.DamageDealt = %d, want 17 (did not survive restore)", got)
	}
	if got := env.G.RewardAccum[1].ShieldAbsorbed; got != 5 {
		t.Errorf("after Restore, P1.ShieldAbsorbed = %d, want 5", got)
	}
}

// TestRewardEvents_DeepCopyIndependent: DeepCopy must produce a clone
// whose RewardAccum is byte-equal to the source, but whose subsequent
// mutations are isolated from the source.
func TestRewardEvents_DeepCopyIndependent(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.G.RewardAccum[0].DamageDealt = 11
	env.G.RewardAccum[1].Kills = 2

	clone := env.G.DeepCopy()
	if clone.RewardAccum[0].DamageDealt != 11 || clone.RewardAccum[1].Kills != 2 {
		t.Fatalf("clone did not carry source RewardAccum: %+v", clone.RewardAccum)
	}

	// Mutating clone must not leak back into source.
	clone.RewardAccum[0].DamageDealt = 999
	if env.G.RewardAccum[0].DamageDealt != 11 {
		t.Errorf("source RewardAccum leaked from clone mutation: got %d, want 11",
			env.G.RewardAccum[0].DamageDealt)
	}
}

// TestRewardEvents_SetAliveCreditsKillerAndVictim: a death must bump
// the opponent's Kills + TotalKills and the victim's Deaths +
// TotalDeaths.
func TestRewardEvents_SetAliveCreditsKillerAndVictim(t *testing.T) {
	env := NewGame(t, []string{"赤蝶", "墨客"}, []string{"猫咪", "刻师傅"})
	// Kill P1's char 0 via the direct engine API so the test doesn't
	// depend on balance / dice / elemental match-ups. SetAlive is the
	// only path that increments the kill/death counters.
	env.G.SetAlive(1, 0, false)

	if got := env.G.RewardAccum[0].Kills; got != 1 {
		t.Errorf("P0.Kills = %d, want 1", got)
	}
	if got := env.G.RewardAccum[0].TotalKills; got != 1 {
		t.Errorf("P0.TotalKills = %d, want 1", got)
	}
	if got := env.G.RewardAccum[1].Deaths; got != 1 {
		t.Errorf("P1.Deaths = %d, want 1", got)
	}
	if got := env.G.RewardAccum[1].TotalDeaths; got != 1 {
		t.Errorf("P1.TotalDeaths = %d, want 1", got)
	}
}

// TestRewardEvents_FieldCountConstant pins the 14-field contract that
// the capi export + Python buffer sizing both depend on.
func TestRewardEvents_FieldCountConstant(t *testing.T) {
	if engine.RewardEventsFieldCount != 14 {
		t.Errorf("RewardEventsFieldCount = %d, want 14", engine.RewardEventsFieldCount)
	}
}
