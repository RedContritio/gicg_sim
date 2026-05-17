package tests

// TestClorindeBasicSpike — ADR-0019 §A.3 Phase 2 — 克洛琳德 角色 lua
// 实施验证。当前 lua DSL 不能完整实现 ref/genius-invokation 中的 cancelHealed
// hook + BondOfLife 完整治疗转换 + 普攻 deductVoid;本 spike 仅验证已实施
// 部分能跑:
//
//   - 加载成功 (3 skill files + char header + Pneuma marker)
//   - 普攻 (逐影之誓) 1 物理伤害正常出
//   - 残光将终 1 次后 生命之契 = 4
//   - 战技 (狩夜之巡) 移除生命之契并造电伤 + 治疗,附夜巡 status
//   - 夜巡 status 下普攻 物理→雷 + 自附 2 层生命之契

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestClorindeBasicSpike(t *testing.T) {
	t.Skip("v_phase2 restructure: 克洛琳德 lua 重写为 v_phase2/ 严格字段对照版,生命之契 / 夜巡 / Pneuma marker 机制 deferred;原 spike 暂搁,机制完整实现后重新启用。字段一致性见 TestVPhase2CharFieldLocks/克洛琳德。")
	env := NewGameWithDeck(t, []string{"克洛琳德"}, []string{"墨客"})
	g := env.G

	// Counter 索引
	var lifeBondID, archeID, vigilActiveID int = -1, -1, -1
	// 生命之契 / 夜巡_active 是 Scope.Self 但 CounterNames 用 bare name;
	// 注意 Self 计数器有多个绑定(每个角色一份),first match 给我们的就是 Clorinde 的那份(P0/C0)
	for id, name := range g.CounterNames {
		switch name {
		case "生命之契":
			if lifeBondID < 0 {
				lifeBondID = id
			}
		case "始基标记": // arche.lua 给 _arche_marker 设了 display="始基标记"
			archeID = id
		case "夜巡_active":
			if vigilActiveID < 0 {
				vigilActiveID = id
			}
		}
	}
	if lifeBondID < 0 || archeID < 0 || vigilActiveID < 0 {
		t.Fatalf("counters: 生命之契=%d 始基标记=%d 夜巡_active=%d",
			lifeBondID, archeID, vigilActiveID)
	}

	clorinde := env.RT.Chars.BySlot[0][0]
	moke := env.RT.Chars.BySlot[1][0]
	if clorinde.Name != "克洛琳德" || moke.Name != "墨客" {
		t.Fatalf("char binding wrong: P0=%s P1=%s", clorinde.Name, moke.Name)
	}

	// Skill ID 索引 (P0 克洛琳德 拥有的 skills)
	var oathID, vigilSkillID, lastLightID int = -1, -1, -1
	for id, sk := range env.RT.Skills.ByID {
		if sk.CharName != "克洛琳德" {
			continue
		}
		switch sk.Name {
		case "逐影之誓":
			oathID = id
		case "狩夜之巡":
			vigilSkillID = id
		case "残光将终":
			lastLightID = id
		}
	}
	if oathID < 0 || vigilSkillID < 0 || lastLightID < 0 {
		t.Fatalf("skills: 逐影之誓=%d 狩夜之巡=%d 残光将终=%d",
			oathID, vigilSkillID, lastLightID)
	}

	// 给 Clorinde 注入足额能量便于直接放爆发
	g.WriteCounter(clorinde.EnergyCounterID, engine.OpSet, 2)

	mokeHpID := moke.HPCounterID
	clorindeHpID := clorinde.HPCounterID
	mokeHpStart := g.Counters[mokeHpID].Value

	// 用 lua invoke_skill 触发(继承 actor=P0/C0 from PushEvent)
	invokeSkill := func(t *testing.T, skillID int) {
		t.Helper()
		g.PushEvent(engine.EventFrame{
			ActionCtx: engine.ActUseSkill,
			Player:    0,
			Char:      0,
		})
		src := fmt.Sprintf("invoke_skill(%d)", skillID)
		if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
			t.Fatalf("invoke_skill exec: %v", err)
		}
		g.PopEvent()
	}

	// Case 1: 普攻 (无夜巡) — 1 物理伤害,Pneuma marker 出口被 reset 到 None
	invokeSkill(t, oathID)
	dmgDealt := mokeHpStart - g.Counters[mokeHpID].Value
	if dmgDealt != 1 {
		t.Errorf("Case 1: 普攻 物理 1, got %d", dmgDealt)
	}
	if g.Counters[archeID].Value != 0 {
		t.Errorf("Case 1: arche marker should reset to None=0, got %d", g.Counters[archeID].Value)
	}

	// Case 2: 残光将终 — 3 雷伤 + 4 层生命之契
	mokeHpBefore2 := g.Counters[mokeHpID].Value
	invokeSkill(t, lastLightID)
	dmg2 := mokeHpBefore2 - g.Counters[mokeHpID].Value
	if dmg2 < 3 {
		t.Errorf("Case 2: 残光将终 至少 3 雷, got %d", dmg2)
	}
	if g.Counters[lifeBondID].Value != 4 {
		t.Errorf("Case 2: 残光将终 后生命之契 = 4, got %d", g.Counters[lifeBondID].Value)
	}

	// Case 3: 狩夜之巡 — 附夜巡, 移除 4 层生命之契并造 4 电伤 + 治疗 4
	mokeHpBefore3 := g.Counters[mokeHpID].Value
	clorindeHpBefore3 := g.Counters[clorindeHpID].Value
	invokeSkill(t, vigilSkillID)
	if g.Counters[vigilActiveID].Value != 1 {
		t.Errorf("Case 3: 夜巡_active = 1, got %d", g.Counters[vigilActiveID].Value)
	}
	if g.Counters[lifeBondID].Value != 0 {
		t.Errorf("Case 3: 战技后生命之契应清零, got %d", g.Counters[lifeBondID].Value)
	}
	dmg3 := mokeHpBefore3 - g.Counters[mokeHpID].Value
	if dmg3 < 4 {
		t.Errorf("Case 3: 战技应造 ≥4 电伤 (4 层契), got %d", dmg3)
	}
	healAmt := g.Counters[clorindeHpID].Value - clorindeHpBefore3
	if healAmt < 0 {
		t.Errorf("Case 3: 治疗后 HP 不应下降, got delta=%d", healAmt)
	}

	// Case 4: 夜巡 status 下普攻 — 物理 → 雷,普攻自附 2 层生命之契
	mokeHpBefore4 := g.Counters[mokeHpID].Value
	invokeSkill(t, oathID)
	dmg4 := mokeHpBefore4 - g.Counters[mokeHpID].Value
	if dmg4 < 1 {
		t.Errorf("Case 4: 夜巡 普攻 应造 ≥1 雷伤, got %d", dmg4)
	}
	if g.Counters[lifeBondID].Value < 2 {
		t.Errorf("Case 4: 夜巡 普攻 后生命之契 ≥2, got %d", g.Counters[lifeBondID].Value)
	}
}
