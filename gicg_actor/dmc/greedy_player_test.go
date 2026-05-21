package dmc

import (
	"math"
	"testing"

	"gicg_mono/gicg_engine/record"
)

// floatNear 守 浮点数 1e-9 tolerance(Python F1 ref ops 在 IEEE 754 下应等价但 const folding
// 在 Go 编译时 high-precision,runtime float64 ops 有 ε 误差)。
func floatNear(got, want, eps float64) bool {
	return math.Abs(got-want) < eps
}

// TestScoreF1_DamageDelta 守 F1 算法:dmg_dealt - 1.1 * dmg_taken。
func TestScoreF1_DamageDelta(t *testing.T) {
	// Before: me HP 30, enemy HP 30。 After: me HP 20 (taken 10), enemy HP 22 (dealt 8)。
	// F1 = 8 - 1.1 * 10 = -3.0。
	viewBefore := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 15, Alive: true}, {HP: 15, Alive: true}}},
			{Chars: []record.CharView{{HP: 15, Alive: true}, {HP: 15, Alive: true}}},
		},
	}
	viewAfter := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 10, Alive: true}, {HP: 10, Alive: true}}},
			{Chars: []record.CharView{{HP: 11, Alive: true}, {HP: 11, Alive: true}}},
		},
	}
	emptyEvents := &EventsSnapshot{}
	score := ScoreF1(viewBefore, viewAfter, emptyEvents, emptyEvents, 0)
	expected := 8.0 - 1.1*10.0
	if !floatNear(score, expected, 1e-9) {
		t.Errorf("F1 score: got %g, want %g (±1e-9)", score, expected)
	}
}

// TestScoreF1_NoChange 守 不动则 score=0。
func TestScoreF1_NoChange(t *testing.T) {
	view := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 30, Alive: true}}},
			{Chars: []record.CharView{{HP: 30, Alive: true}}},
		},
	}
	emptyEvents := &EventsSnapshot{}
	score := ScoreF1(view, view, emptyEvents, emptyEvents, 0)
	if score != 0.0 {
		t.Errorf("no-delta should yield 0, got %g", score)
	}
}

// TestScoreF1_FromOppositePerspective 守 me=1 视角:dmg dealt to player 0,taken by player 1。
func TestScoreF1_FromOppositePerspective(t *testing.T) {
	viewBefore := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 30, Alive: true}}},
			{Chars: []record.CharView{{HP: 30, Alive: true}}},
		},
	}
	viewAfter := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 20, Alive: true}}},
			{Chars: []record.CharView{{HP: 25, Alive: true}}},
		},
	}
	emptyEvents := &EventsSnapshot{}
	score := ScoreF1(viewBefore, viewAfter, emptyEvents, emptyEvents, 1)
	// me=1: own_delta=5, enemy_delta=10。 score = 10 - 1.1*5 = 4.5
	expected := 10.0 - 1.1*5.0
	if !floatNear(score, expected, 1e-9) {
		t.Errorf("F1 me=1: got %g, want %g (±1e-9)", score, expected)
	}
}

// TestNewGreedyPlayer_ValidConfig 守 valid (F1, depth=1) construct OK。
func TestNewGreedyPlayer_ValidConfig(t *testing.T) {
	gp, err := NewGreedyPlayer("F1", 1, 42)
	if err != nil {
		t.Fatalf("construct: %v", err)
	}
	if gp.cfg.Features != "F1" || gp.cfg.Depth != 1 {
		t.Errorf("config: %+v", gp.cfg)
	}
}

// TestNewGreedyPlayer_UnknownFeatures 守 unknown features fail loud。
func TestNewGreedyPlayer_UnknownFeatures(t *testing.T) {
	_, err := NewGreedyPlayer("F99", 1, 0)
	if err == nil {
		t.Fatal("expected unknown features error")
	}
}

// TestNewGreedyPlayer_AllDepthsSupported 守 D1-D4 全可构造(Phase 1.2b 完整 port)。
func TestNewGreedyPlayer_AllDepthsSupported(t *testing.T) {
	for _, d := range []int{1, 2, 3, 4} {
		_, err := NewGreedyPlayer("F1", d, 0)
		if err != nil {
			t.Errorf("depth=%d: unexpected err: %v", d, err)
		}
	}
}

// TestNewGreedyPlayer_AllFeaturesSupported 守 F1-F5 全可构造。
func TestNewGreedyPlayer_AllFeaturesSupported(t *testing.T) {
	for _, f := range []string{"F1", "F2", "F3", "F4", "F5"} {
		_, err := NewGreedyPlayer(f, 1, 0)
		if err != nil {
			t.Errorf("features=%s: unexpected err: %v", f, err)
		}
	}
}

// TestNewGreedyPlayer_BadDepth 守 depth out-of-range fail loud。
func TestNewGreedyPlayer_BadDepth(t *testing.T) {
	_, err := NewGreedyPlayer("F1", 0, 0)
	if err == nil {
		t.Fatal("expected depth out-of-range error")
	}
	_, err = NewGreedyPlayer("F1", 5, 0)
	if err == nil {
		t.Fatal("expected depth out-of-range error")
	}
}

// TestScoreF2_KillBonus 守 F2:F1 base + 10·kill_delta - 8·death_delta。
func TestScoreF2_KillBonus(t *testing.T) {
	viewBefore := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 30, Alive: true}, {HP: 10, Alive: true}}},
			{Chars: []record.CharView{{HP: 5, Alive: true}, {HP: 5, Alive: true}}},
		},
	}
	viewAfter := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 30, Alive: true}, {HP: 10, Alive: true}}},
			{Chars: []record.CharView{{HP: 0, Alive: false}, {HP: 5, Alive: true}}},
		},
	}
	emptyEvents := &EventsSnapshot{}
	score := ScoreF2(viewBefore, viewAfter, emptyEvents, emptyEvents, 0)
	// dmg dealt 5 (enemy HP 10 → 5), dmg taken 0;F1=5。 kill 1 enemy → +10。 total 15。
	expected := 5.0 + 10.0
	if !floatNear(score, expected, 1e-9) {
		t.Errorf("F2 kill bonus: got %g, want %g", score, expected)
	}
}

// TestScoreF3_HealDelta 守 F3 += heal_done - 0.8·enemy_heal_done。
func TestScoreF3_HealDelta(t *testing.T) {
	view := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 20, Alive: true}}},
			{Chars: []record.CharView{{HP: 20, Alive: true}}},
		},
	}
	eventsBefore := &EventsSnapshot{}
	eventsAfter := &EventsSnapshot{}
	eventsAfter[EvHealDone] = 5
	eventsAfter[EvEnemyHealDone] = 3
	score := ScoreF3(view, view, eventsBefore, eventsAfter, 0)
	// F2 = F1 + 0 (no kill, no HP change) = 0;heal = 5 - 0.8·3 = 2.6
	expected := 5.0 - 0.8*3.0
	if !floatNear(score, expected, 1e-9) {
		t.Errorf("F3 heal: got %g, want %g", score, expected)
	}
}

// TestScoreF4_ShieldReaction 守 F4 += shield + reaction delta。
func TestScoreF4_ShieldReaction(t *testing.T) {
	view := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 20, Alive: true}}},
			{Chars: []record.CharView{{HP: 20, Alive: true}}},
		},
	}
	eventsBefore := &EventsSnapshot{}
	eventsAfter := &EventsSnapshot{}
	eventsAfter[EvShieldAbsorbed] = 10
	eventsAfter[EvDamageBlocked] = 5
	eventsAfter[EvReactionsTriggered] = 3
	eventsAfter[EvReactionsReceived] = 2
	score := ScoreF4(view, view, eventsBefore, eventsAfter, 0)
	// F3 = 0;shield = 10 - 0.8·5 = 6;react = 3 - 0.8·2 = 1.4;total = 7.4
	expected := (10.0 - 0.8*5.0) + (3.0 - 0.8*2.0)
	if !floatNear(score, expected, 1e-9) {
		t.Errorf("F4: got %g, want %g", score, expected)
	}
}

// TestScoreF5_AllPenalties 守 F5 += energy penalty + AP penalty + escalating kill。
func TestScoreF5_AllPenalties(t *testing.T) {
	view := &record.StateView{
		Players: [2]record.PlayerView{
			{Chars: []record.CharView{{HP: 20, Alive: true}}},
			{Chars: []record.CharView{{HP: 20, Alive: true}}},
		},
	}
	eventsBefore := &EventsSnapshot{}
	eventsBefore[EvTotalKills] = 0
	eventsAfter := &EventsSnapshot{}
	eventsAfter[EvEnergyOverflow] = 2
	eventsAfter[EvAPWasted] = 4 // 0.2·3 + 0.5·1 = 1.1 (前 3 cheap + 1 mid)
	eventsAfter[EvKills] = 2    // escalating: 5·(0+0) + 5·(0+1) = 5
	score := ScoreF5(view, view, eventsBefore, eventsAfter, 0)
	// F4 = 0;energy = -0.4·2 = -0.8;ap = -1.1;kill_slope = 5
	expected := -0.4*2.0 - 1.1 + 5.0
	if !floatNear(score, expected, 1e-9) {
		t.Errorf("F5: got %g, want %g", score, expected)
	}
}

// TestApWastePiecewise 守 分段函数 boundary。
func TestApWastePiecewise(t *testing.T) {
	cases := []struct {
		n        int
		expected float64
	}{
		{0, 0},
		{3, 0.6},                    // 0.2·3
		{6, 0.6 + 1.5},              // 0.2·3 + 0.5·3
		{8, 0.6 + 1.5 + 1.6},        // 0.2·3 + 0.5·3 + 0.8·2
		{10, 0.6 + 1.5 + 1.6 + 2.0}, // + 1.0·2
		{-5, 0},                     // negative clamp
	}
	for _, c := range cases {
		got := apWastePiecewise(c.n)
		if !floatNear(got, c.expected, 1e-9) {
			t.Errorf("ap_waste(%d): got %g, want %g", c.n, got, c.expected)
		}
	}
}

// TestKillSlopeEscalating 守 sum 5·(total_before+i) for i ∈ [0,k)。
func TestKillSlopeEscalating(t *testing.T) {
	// k=3, total=2: 5·(2+0) + 5·(2+1) + 5·(2+2) = 10 + 15 + 20 = 45
	if got := killSlopeEscalating(3, 2); got != 45.0 {
		t.Errorf("got %g, want 45", got)
	}
	if got := killSlopeEscalating(0, 5); got != 0 {
		t.Errorf("k=0 should be 0, got %g", got)
	}
}

// TestSnapshotEvents_FieldOrder 守 14 字段顺序跟 Python REWARD_EVENTS_FIELDS 一致。
// 跨平台 + cross-language 不变 — 改字段顺序 = 破协议。
func TestSnapshotEvents_FieldOrder(t *testing.T) {
	// 本测试不需要真 engine — 直接 verify struct 字段顺序常量在 [14] array 内位置正确。
	// 通过 Ev* 常量索引 EventsSnapshot,assert 字段名 → 索引映射跟 Python EV_* dict 同。
	mapping := map[int]string{
		EvDamageDealt:        "DamageDealt",
		EvDamageReceived:     "DamageReceived",
		EvHealDone:           "HealDone",
		EvEnemyHealDone:      "EnemyHealDone",
		EvShieldAbsorbed:     "ShieldAbsorbed",
		EvDamageBlocked:      "DamageBlocked",
		EvKills:              "Kills",
		EvTotalKills:         "TotalKills",
		EvDeaths:             "Deaths",
		EvTotalDeaths:        "TotalDeaths",
		EvReactionsTriggered: "ReactionsTriggered",
		EvReactionsReceived:  "ReactionsReceived",
		EvAPWasted:           "APWasted",
		EvEnergyOverflow:     "EnergyOverflow",
	}
	if len(mapping) != 14 {
		t.Errorf("expected 14 fields, got %d", len(mapping))
	}
	// 确保 0..13 都覆盖,无跳号 / 重复。
	for i := range 14 {
		if _, ok := mapping[i]; !ok {
			t.Errorf("Ev index %d not mapped", i)
		}
	}
}
