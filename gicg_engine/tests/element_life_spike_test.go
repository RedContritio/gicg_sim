package tests

// TestPyrohelminthSpike — ADR-0019 §A.3 Phase 2 — 陆行岩本真蕈 状态机
// (陆地优势 / 枯焦 / 活化) 验证。
//
// TestWaterSlimeSpike — ADR-0019 §A.3 Phase 2 — 水史莱姆 元素生命·水
// (总附着 + 免疫水元素伤害) 验证。
//
// 两个 entity 都验证 buff-owned 状态切换协议:被动 hook 在 char 自己
// file 内,不入 system/。

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestPyrohelminthSpike(t *testing.T) {
	t.Skip("v_phase2 restructure: 陆行岩本真蕈 是 monster,v_phase2/characters/ 仅收 character;状态机机制 deferred,后续若建 monsters/ 池再恢复。")
	env := NewGameWithDeck(t, []string{"陆行岩本真蕈"}, []string{"赤蝶"})
	g := env.G

	helm := env.RT.Chars.BySlot[0][0]
	chidie := env.RT.Chars.BySlot[1][0]
	if helm.Name != "陆行岩本真蕈" || chidie.Name != "赤蝶" {
		t.Fatalf("char binding wrong: P0=%s P1=%s", helm.Name, chidie.Name)
	}

	var stateID int = -1
	for id, name := range g.CounterNames {
		if name == "陆行岩状态" {
			stateID = id
			break
		}
	}
	if stateID < 0 {
		t.Fatalf("陆行岩状态 counter 未找到")
	}

	var sporeID int = -1
	for id, sk := range env.RT.Skills.ByID {
		if sk.CharName == "陆行岩本真蕈" && sk.Name == "孢子弹" {
			sporeID = id
			break
		}
	}
	if sporeID < 0 {
		t.Fatalf("孢子弹 skill 未找到")
	}

	chidieHpID := chidie.HPCounterID
	helmHpID := helm.HPCounterID

	// Case 1: 陆地优势 (默认状态 0) — 普攻 1 岩 + 1 加成 = 2 岩伤
	// 但目标是赤蝶 (火元素),岩+火无反应,期望直接 2 伤
	chidieHpStart := g.Counters[chidieHpID].Value
	g.PushEvent(engine.EventFrame{ActionCtx: engine.ActUseSkill, Player: 0, Char: 0})
	src := fmt.Sprintf("invoke_skill(%d)", sporeID)
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatalf("invoke 孢子弹: %v", err)
	}
	g.PopEvent()
	dmg1 := chidieHpStart - g.Counters[chidieHpID].Value
	if dmg1 != 2 {
		t.Errorf("Case 1: 陆地优势 普攻 1 岩 + 1 加成 = 2,got %d", dmg1)
	}

	// Case 2: 受 火元素 攻击 → 状态切换到 枯焦 (=1)
	g.PushEvent(engine.EventFrame{ActionCtx: engine.ActUseSkill, Player: 1, Char: 0})
	g.DealDamage(helmHpID, engine.ElemFire, 1, engine.DamageOpts{
		ActorPlayer: 1, ActorChar: 0,
	})
	g.PopEvent()
	if g.Counters[stateID].Value != 1 {
		t.Errorf("Case 2: 受火 → 枯焦(1), got %d", g.Counters[stateID].Value)
	}

	// Case 3: 枯焦状态下 普攻 — 失去加成 (1 岩,无 +1)
	chidieHpBefore3 := g.Counters[chidieHpID].Value
	g.PushEvent(engine.EventFrame{ActionCtx: engine.ActUseSkill, Player: 0, Char: 0})
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatalf("invoke 孢子弹 #2: %v", err)
	}
	g.PopEvent()
	dmg3 := chidieHpBefore3 - g.Counters[chidieHpID].Value
	if dmg3 != 1 {
		t.Errorf("Case 3: 枯焦 普攻 1 岩 (无加成),got %d", dmg3)
	}

	// Case 4: 受 雷元素 攻击 → 状态切换到 活化 (=2)
	// 注意:火→枯焦后再受雷,per game text "永久切换" 应切到活化
	g.PushEvent(engine.EventFrame{ActionCtx: engine.ActUseSkill, Player: 1, Char: 0})
	g.DealDamage(helmHpID, engine.ElemElectro, 1, engine.DamageOpts{
		ActorPlayer: 1, ActorChar: 0,
	})
	g.PopEvent()
	if g.Counters[stateID].Value != 2 {
		t.Errorf("Case 4: 受雷 → 活化(2), got %d", g.Counters[stateID].Value)
	}
}

func TestWaterSlimeSpike(t *testing.T) {
	t.Skip("v_phase2 restructure: 水史莱姆 是 monster,v_phase2/characters/ 仅收 character;元素生命·水 机制 deferred,后续若建 monsters/ 池再恢复。")
	env := NewGameWithDeck(t, []string{"水史莱姆"}, []string{"赤蝶"})
	g := env.G

	slime := env.RT.Chars.BySlot[0][0]
	if slime.Name != "水史莱姆" {
		t.Fatalf("char binding wrong: P0=%s", slime.Name)
	}

	slimeHpID := slime.HPCounterID
	slimeHpStart := g.Counters[slimeHpID].Value

	// Case 1: 水免疫 — 给水史莱姆造 3 水伤,免疫,HP 不变
	g.PushEvent(engine.EventFrame{ActionCtx: engine.ActUseSkill, Player: 1, Char: 0})
	g.DealDamage(slimeHpID, engine.ElemWater, 3, engine.DamageOpts{
		ActorPlayer: 1, ActorChar: 0,
	})
	g.PopEvent()
	if g.Counters[slimeHpID].Value != slimeHpStart {
		t.Errorf("Case 1: 水史莱姆 应免疫水伤, HP %d → %d", slimeHpStart, g.Counters[slimeHpID].Value)
	}

	// Case 2: 非水伤害正常 — 给 1 火伤,实际还触发蒸发反应 (水附着 + 火攻击)
	// 水史莱姆有水附着 (来自被动总附着 — round_start 时刷新);蒸发会
	// 改变 ctx.element,但 HP 仍应下降。
	hpBefore2 := g.Counters[slimeHpID].Value
	g.PushEvent(engine.EventFrame{ActionCtx: engine.ActUseSkill, Player: 1, Char: 0})
	g.DealDamage(slimeHpID, engine.ElemFire, 1, engine.DamageOpts{
		ActorPlayer: 1, ActorChar: 0,
	})
	g.PopEvent()
	dmg2 := hpBefore2 - g.Counters[slimeHpID].Value
	if dmg2 < 1 {
		t.Errorf("Case 2: 火伤应造 ≥1, got %d", dmg2)
	}
}
