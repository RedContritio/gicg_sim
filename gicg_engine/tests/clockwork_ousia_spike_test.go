package tests

// TestClockworkOusiaSpike — ADR-0019 §A.3 Phase 2 — 攻坚特化型机关·荒
// 角色 lua + 始基反应 (Pneuma 攻击 → 失能形态) 端到端验证。
//
// 配套 克洛琳德 (Pneuma marker on damage_type) + 攻坚机关·荒 (Ousia
// 能源特征 + after_damage 检测) 完整闭环 — 该测试是 §A.3 Phase 2 真
// 始基反应在双 char file 中跨 binding 协作的首次实证。
//
// 简化:实际游戏 失能形态 持续到本回合结束 + 切换技能集 (失能形态
// 版本的近距格斗等);本实施仅做 1 回合 disabled 标志 + 本回合 reject
// skills,失能技能集 deferred。

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestClockworkOusiaSpike(t *testing.T) {
	t.Skip("v_phase2 restructure: 攻坚特化型机关·荒 是 monster (parent_class=monster),v_phase2/characters/ 仅收 character;monster lua 已从 v_legacy/characters/ 删除。始基反应机制 deferred,后续若建 monsters/ 池或独立机制 spike pool 再恢复。")
	// P0 = 克洛琳德 (Pneuma attacker), P1 = 攻坚机关·荒 (Ousia target)
	env := NewGameWithDeck(t, []string{"克洛琳德"}, []string{"攻坚特化型机关·荒"})
	g := env.G

	clorinde := env.RT.Chars.BySlot[0][0]
	clockwork := env.RT.Chars.BySlot[1][0]
	if clorinde.Name != "克洛琳德" || clockwork.Name != "攻坚特化型机关·荒" {
		t.Fatalf("char binding wrong: P0=%s P1=%s", clorinde.Name, clockwork.Name)
	}

	// counter 索引
	var disabledID, archeID int = -1, -1
	for id, name := range g.CounterNames {
		switch name {
		case "失能形态":
			disabledID = id
		case "始基标记":
			archeID = id
		}
	}
	if disabledID < 0 || archeID < 0 {
		t.Fatalf("counters: 失能形态=%d 始基标记=%d", disabledID, archeID)
	}

	// 找 Clorinde 的普攻 + 机关·荒 的普攻
	var oathID, bashID int = -1, -1
	for id, sk := range env.RT.Skills.ByID {
		if sk.CharName == "克洛琳德" && sk.Name == "逐影之誓" {
			oathID = id
		}
		if sk.CharName == "攻坚特化型机关·荒" && sk.Name == "近距格斗" {
			bashID = id
		}
	}
	if oathID < 0 || bashID < 0 {
		t.Fatalf("skills: 逐影之誓=%d 近距格斗=%d", oathID, bashID)
	}

	invokeSkill := func(t *testing.T, p, c, skillID int) {
		t.Helper()
		g.PushEvent(engine.EventFrame{
			ActionCtx: engine.ActUseSkill,
			Player:    p,
			Char:      c,
		})
		src := fmt.Sprintf("invoke_skill(%d)", skillID)
		if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
			t.Fatalf("invoke_skill exec: %v", err)
		}
		g.PopEvent()
	}

	// Pre-condition: 失能形态 = 0
	if g.Counters[disabledID].Value != 0 {
		t.Fatalf("init: 失能形态 应 0, got %d", g.Counters[disabledID].Value)
	}

	// Case 1: 克洛琳德 (Pneuma) 普攻 攻坚机关·荒 (Ousia) → 触发湮灭 → 失能形态=1
	invokeSkill(t, 0, 0, oathID)
	if g.Counters[disabledID].Value != 1 {
		t.Errorf("Case 1: Pneuma → Ousia 应触发失能形态, got %d", g.Counters[disabledID].Value)
	}

	// Case 2: 失能形态 期间 机关·荒 普攻应被 reject (action_check playable=false)
	// 直接构造 ctx 做 action_check 验证
	checkCtx := &engine.EventContext{
		ActionCtx:   engine.ActUseSkill,
		ActorPlayer: 1,
		ActorChar:   0,
		SkillIndex:  bashID,
		ActionKind:  engine.ActionSkill,
		Playable:    true,
	}
	g.FireEventHooks(engine.HookActionCheck, checkCtx)
	if checkCtx.Playable {
		t.Errorf("Case 2: 失能形态 期间 ctx.playable 应 false, got true")
	}

	// Case 3: 同性 (Ousia attacker vs Ousia target) 不触发 — 但当前测试是
	// Clorinde (Pneuma) 攻击,不能直接验同性。改用 inline DSL 模拟 Ousia
	// attacker 攻击 攻坚机关·荒,验 不触发。
	// reset 失能形态
	g.WriteCounter(disabledID, engine.OpSet, 0)
	g.WriteCounter(archeID, engine.OpSet, int(2)) // Arkhe.Ousia (= 攻击方也是 Ousia, 同性)

	clockworkHpID := clockwork.HPCounterID
	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(clockworkHpID, engine.ElemPhysical, 1, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	if g.Counters[disabledID].Value != 0 {
		t.Errorf("Case 3: Ousia attacker vs Ousia target 同性不触发, 失能形态 = %d, want 0", g.Counters[disabledID].Value)
	}
}
