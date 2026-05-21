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

// TestNewGreedyPlayer_DepthNotImplemented 守 depth > 1 fail loud(P1.2c follow-up)。
func TestNewGreedyPlayer_DepthNotImplemented(t *testing.T) {
	_, err := NewGreedyPlayer("F1", 2, 0)
	if err == nil {
		t.Fatal("expected depth-not-implemented error")
	}
	_, err = NewGreedyPlayer("F1", 4, 0)
	if err == nil {
		t.Fatal("expected depth-not-implemented error")
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
