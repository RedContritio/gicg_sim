package tests

// 以逸待劳治疗与护盾反击：真实卡牌链路、双方席位。

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

// --- 4a. 治疗等量反击(真卡路径,双 owner 席位) ---
//
// 治疗源用 猫咪_甜美领域 的回合末领域治疗(heal Target.OwnActive,
// per-player 帧,双席位帧语义正确)。美味烧鸡的旧 CardTarget 错靶
// 已修复并由 current_cards_targets_test.go 覆盖;这里保留回合末链路。
//
// 回合末序列:领域 heal 出战 +2 → 以逸待劳 反击 2 冰伤(猫咪元素)
// → 领域自身 1 冰伤,敌方出战合计 -3。

func TestYiYiDaiLao_HealCounter_P0Owner(t *testing.T) {
	env := NewGame(t, []string{"猫咪"}, []string{"赤蝶"})
	// 预伤自家出战角色,让回合末 heal 真实回血
	env.G.Counters[env.RT.Chars.BySlot[0][0].HPCounterID].Value -= 4

	giveCard(t, env, 0, "以逸待劳")
	env.SetDice(0, map[int]int{int(engine.DiceColorOmni): 8})
	playCard(t, env, "以逸待劳") // battle → P1
	env.StepEndTurn()        // P1 declare end → P0

	env.G.Counters[env.RT.Chars.BySlot[0][0].EnergyCounterID].Value = 3
	env.SetDice(0, map[int]int{int(engine.DiceColorIce): 3})
	if !env.StepSkill("甜美领域") { // 2 冰伤 + 召唤领域;P1 已 declare → turn 留 P0
		t.Fatal("甜美领域 not offered")
	}

	maoBefore := env.HP(0, 0)
	chiBefore := env.HP(1, 0)
	env.StepEndTurn() // P0 declare end → 回合结算
	_ = env.G.GetLegalActions()

	if got := env.HP(0, 0) - maoBefore; got != 2 {
		t.Errorf("猫咪 HP delta = %d, want +2 (领域回合末治疗)", got)
	}
	if got := env.HP(1, 0) - chiBefore; got != -3 {
		t.Errorf("赤蝶 HP delta = %d, want -3 (以逸待劳 治疗等量反击 2 冰 + 领域 1 冰)", got)
	}
}

func TestYiYiDaiLao_HealCounter_P1Owner(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"猫咪"})
	env.G.Counters[env.RT.Chars.BySlot[1][0].HPCounterID].Value -= 4

	env.StepEndTurn() // P0 declare end → P1
	giveCard(t, env, 1, "以逸待劳")
	env.SetDice(1, map[int]int{int(engine.DiceColorOmni): 8})
	playCard(t, env, "以逸待劳") // battle;P0 已 declare → turn 留 P1

	env.G.Counters[env.RT.Chars.BySlot[1][0].EnergyCounterID].Value = 3
	env.SetDice(1, map[int]int{int(engine.DiceColorIce): 3})
	if !env.StepSkill("甜美领域") {
		t.Fatal("甜美领域 not offered")
	}

	maoBefore := env.HP(1, 0)
	chiBefore := env.HP(0, 0)
	env.StepEndTurn() // P1 declare end → 回合结算
	_ = env.G.GetLegalActions()

	if got := env.HP(1, 0) - maoBefore; got != 2 {
		t.Errorf("猫咪 HP delta = %d, want +2 (领域回合末治疗)", got)
	}
	if got := env.HP(0, 0) - chiBefore; got != -3 {
		t.Errorf("赤蝶 HP delta = %d, want -3 (以逸待劳 治疗等量反击 2 冰 + 领域 1 冰)", got)
	}
}

// --- 4b. 护盾吸收等量反击(真卡路径,双 owner 席位) ---

// P0 owner:墨客挂 荷花酥(>2 伤全免)+ 以逸待劳;P1 赤蝶 回火 4 火伤
// 被全吸收 → 反击 4 水伤(墨客元素)至攻击方出战。
func TestYiYiDaiLao_AbsorbCounter_P0Owner(t *testing.T) {
	env := NewGame(t, []string{"墨客"}, []string{"赤蝶"})
	giveCard(t, env, 0, "以逸待劳")
	giveCard(t, env, 0, "荷花酥")
	env.SetDice(0, map[int]int{int(engine.DiceColorOmni): 10})
	playCard(t, env, "荷花酥")  // fast → turn 留 P0
	playCard(t, env, "以逸待劳") // battle → P1

	env.G.Counters[env.RT.Chars.BySlot[1][0].EnergyCounterID].Value = 3
	env.SetDice(1, map[int]int{int(engine.DiceColorFire): 3})

	moBefore := env.HP(0, 0)
	chiBefore := env.HP(1, 0)
	if !env.StepSkill("回火") {
		t.Fatal("回火 not offered")
	}

	if got := env.HP(0, 0) - moBefore; got != 0 {
		t.Errorf("墨客 HP delta = %d, want 0 (荷花酥全吸收 4 火伤)", got)
	}
	if got := env.HP(1, 0) - chiBefore; got != -4 {
		t.Errorf("赤蝶 HP delta = %d, want -4 (以逸待劳 吸收等量反击 4 水伤)", got)
	}
}

// P1 owner 镜像:P0 赤蝶 先普攻消耗回合(基线后移),P1 墨客挂双卡,
// P0 回火 4 火伤被全吸收 → 反击 4 水伤。
func TestYiYiDaiLao_AbsorbCounter_P1Owner(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 3})
	if !env.StepSkill("枪") { // battle → P1(buff 尚未挂,普攻 2 伤直达)
		t.Fatal("枪 not offered")
	}

	giveCard(t, env, 1, "以逸待劳")
	giveCard(t, env, 1, "荷花酥")
	env.SetDice(1, map[int]int{int(engine.DiceColorOmni): 10})
	playCard(t, env, "荷花酥")  // fast → turn 留 P1
	playCard(t, env, "以逸待劳") // battle → P0

	env.G.Counters[env.RT.Chars.BySlot[0][0].EnergyCounterID].Value = 3
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 3})

	moBefore := env.HP(1, 0)
	chiBefore := env.HP(0, 0)
	if !env.StepSkill("回火") {
		t.Fatal("回火 not offered")
	}

	if got := env.HP(1, 0) - moBefore; got != 0 {
		t.Errorf("墨客 HP delta = %d, want 0 (荷花酥全吸收 4 火伤)", got)
	}
	if got := env.HP(0, 0) - chiBefore; got != -4 {
		t.Errorf("赤蝶 HP delta = %d, want -4 (以逸待劳 吸收等量反击 4 水伤)", got)
	}
}
