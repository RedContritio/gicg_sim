package tests

// TestPrepareSkillSpike — ADR-0012 spike 验证。歼灭机关 用「高频旋击」
// 触发 set_preparing(超速旋击);engine 应在该方下次 turn 自动 silent
// invoke 超速旋击,造成 1 火伤 + 自身充能 +1。
//
// 测试流程:
//   1. 1v1 mirror 歼灭机关 双方
//   2. P0 高频旋击 → P0.Preparing = 超速旋击 id;turn flip → P1
//   3. P1 普攻 → turn flip → P0(此时 engine 应自动 ResolvePreparing)
//   4. 验证:P0 Preparing == 0;P1 active char HP - 2(高频 1 + 超速 1);
//      P0 active char energy + 1(超速旋击 DSL 加的)

import (
	"testing"
)

func TestPrepareSkillSpike_ResolveOnNextTurn(t *testing.T) {
	// Use 歼灭机关 mirror so we can trigger prepare on P0 then watch
	// the auto-resolve when turn comes back.
	env := NewGameWithDeck(t, []string{"歼灭机关"}, []string{"歼灭机关"})
	g := env.G

	// Initial HP for both active chars.
	p1Hp0 := g.Counters[env.RT.Chars.BySlot[1][0].HPCounterID].Value
	p0Energy0 := g.Counters[env.RT.Chars.BySlot[0][0].EnergyCounterID].Value

	// Find skill IDs by name (rt.Skills.ByID maps id→ref; iterate to find).
	var 高频旋击ID, 超速旋击ID int
	for id, sk := range env.RT.Skills.ByID {
		if sk.Name == "高频旋击" {
			高频旋击ID = id
		}
		if sk.Name == "超速旋击" {
			超速旋击ID = id
		}
	}
	if 高频旋击ID == 0 || 超速旋击ID == 0 {
		t.Fatalf("skills not loaded: 高频=%d 超速=%d", 高频旋击ID, 超速旋击ID)
	}

	// Locate "高频旋击" in P0's legal action list and step it.
	actions := g.GetLegalActions()
	pickIdx := -1
	for i, a := range actions {
		if a.PlayerIdx == 0 && a.Index == 高频旋击ID {
			pickIdx = i
			break
		}
	}
	if pickIdx < 0 {
		t.Fatalf("高频旋击 not in legal actions for P0; actions=%v", actions)
	}
	g.Step(pickIdx)

	// After 高频旋击: P0.Preparing should be 超速旋击, P1 HP -1.
	if g.Preparing[0] != 超速旋击ID {
		t.Errorf("after 高频旋击: P0.Preparing = %d, want %d", g.Preparing[0], 超速旋击ID)
	}
	p1HpAfterHigh := g.Counters[env.RT.Chars.BySlot[1][0].HPCounterID].Value
	if p1HpAfterHigh != p1Hp0-1 {
		t.Errorf("after 高频旋击: P1 HP %d → %d, want -1 damage", p1Hp0, p1HpAfterHigh)
	}

	// P1 takes a turn (use 普攻). After P1's flip → P0's turn → engine
	// should auto-ResolvePreparing on P0 → silent invoke 超速旋击 →
	// P1 HP -1 more, P0 energy +1 → flipTurn → back to P1.
	actions = g.GetLegalActions()
	pickIdx = -1
	for i, a := range actions {
		// P1's normal attack (any skill from P1 actor works).
		if a.PlayerIdx == 1 && a.Kind == 0 /* ActionSkill */ {
			pickIdx = i
			break
		}
	}
	if pickIdx < 0 {
		t.Fatalf("no P1 skill action available; actions=%v", actions)
	}
	g.Step(pickIdx)

	// At this point flipTurn() back to P0 should have auto-resolved.
	if g.Preparing[0] != 0 {
		t.Errorf("after auto-resolve: P0.Preparing = %d, want 0 (cleared)", g.Preparing[0])
	}
	p1HpFinal := g.Counters[env.RT.Chars.BySlot[1][0].HPCounterID].Value
	// 高频(-1) + P1 普攻 不打 P1 + 超速 silent invoke(-1) = -2 total on P1.
	// Actually P1 普攻 hits P0 not P1, so P1 HP 只受 高频 + 超速 = -2.
	if p1HpFinal != p1Hp0-2 {
		t.Errorf("after prepare resolve: P1 HP %d → %d, want -2 from 高频+超速", p1Hp0, p1HpFinal)
	}
	p0EnergyFinal := g.Counters[env.RT.Chars.BySlot[0][0].EnergyCounterID].Value
	// 高频 canonical +1; preparing skips canonical hooks and its DSL adds +1.
	if p0EnergyFinal != p0Energy0+2 {
		t.Errorf("after 高频 + auto-超速: P0 energy %d → %d, want +2", p0Energy0, p0EnergyFinal)
	}
	t.Logf("P0 energy %d → %d", p0Energy0, p0EnergyFinal)
}
