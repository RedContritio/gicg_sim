package tests

// TestArcheMechanismSpike — ADR-0019 §A.3 Phase 2 minimal mechanism spike。
//
// 完整克洛琳德 / 机关·荒 lua 实施超 session 范围(每张需重新写普攻/战技/
// 爆发 + 始基 hook + 失能形态等);本 spike 验证 buff-owned arche 协议
// 可行 — 用 inline DSL 模拟 attacker (设 Arkhe.Ousia marker) + target
// (检测对立 Arkhe.Pneuma 触发湮灭 flag) 端到端机制。
//
// 如果 spike PASS,证明 Phase 1 基础设施(arche.lua + Arkhe enum)足够
// 支撑 Phase 2 完整角色实施;Phase 2 实施时只需写 6 张机关 / 角色的具体
// lua,无需再改 engine。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestArcheMechanismSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"墨客"}, []string{"墨客"})
	g := env.G

	// 模拟 attacker(P0 char 0):on_damage_boost 设 marker=Arkhe.Ousia (荒);
	//                          on_after_damage 出口 reset。
	// 模拟 target(P1 char 0):on_after_damage 检测 actor.Arkhe == Pneuma →
	//                        target 转换"失能形态"(set 一个 flag counter)。
	// 实际机关·荒能源特征 == Ousia,actor 是 Pneuma 才触发湮灭;但本 spike
	// 反向(actor=Ousia, target 检测 Pneuma)也是同一逻辑模式。
	//
	// 我们用 actor=Ousia + target 检测 Ousia(同性,不触发)/ Pneuma(异性,
	// 触发)双 case 验证。

	src := `
local arche = get_counter("_arche_marker", Scope.Global)
local damage_count = declare_counter("damage_count", Scope.Global, 0, { min = 0, max = 100 })
local annihilate_flag = declare_counter("annihilate_flag", Scope.Global, 0, { min = 0, max = 1 })
local detection_arkhe = declare_counter("detection_arkhe", Scope.Global, 0, { min = 0, max = 2 })

-- attacker (P0 char 0) hook: 设 marker=Arkhe.Ousia (strict §B.5: on_damage_type 用于 boost-阶段标记)
on_damage_type(100, function(ctx)
  if ctx.actor_player == 0 and ctx.actor_char == 0 then
    arche:set(Arkhe.Ousia)
  end
end)

-- target (P1 char 0) hook: 检测 actor.Arkhe vs detection_arkhe (能源特征)
-- detection_arkhe == Pneuma 表 target 是芒性,actor=Ousia 触发湮灭
-- detection_arkhe == Ousia 表 target 是荒性,actor=Ousia 同性不触发
on_after_damage(function(ctx)
  if ctx.target_player ~= 1 or ctx.target_char ~= 0 then return end
  damage_count:set(damage_count:get() + 1)
  local actor_arkhe = arche:get()
  local target_signature = detection_arkhe:get()
  if target_signature == Arkhe.None then return end
  -- 相反始基触发湮灭
  if actor_arkhe == Arkhe.Pneuma and target_signature == Arkhe.Ousia then
    annihilate_flag:set(1)
  elseif actor_arkhe == Arkhe.Ousia and target_signature == Arkhe.Pneuma then
    annihilate_flag:set(1)
  end
end)

-- attacker reset hook: 出口清 marker,优先级低
on_after_damage(-100, function(ctx)
  if ctx.actor_player == 0 and ctx.actor_char == 0 then
    arche:set(Arkhe.None)
  end
end)
`

	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatalf("hook setup: %v", err)
	}

	// Find counters
	var detectionArkheID, annihilateFlagID int = -1, -1
	for id, name := range g.CounterNames {
		switch name {
		case "detection_arkhe":
			detectionArkheID = id
		case "annihilate_flag":
			annihilateFlagID = id
		}
	}
	if detectionArkheID < 0 || annihilateFlagID < 0 {
		t.Fatalf("counters not declared: detection=%d annihilate=%d", detectionArkheID, annihilateFlagID)
	}

	// Case 1: target signature = Pneuma (芒) + actor = Ousia (荒) → 触发
	g.WriteCounter(detectionArkheID, engine.OpSet, 1) // Arkhe.Pneuma
	g.WriteCounter(annihilateFlagID, engine.OpSet, 0)

	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPhysical, 1, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	if g.Counters[annihilateFlagID].Value != 1 {
		t.Errorf("Case 1 (Ousia attacker vs Pneuma target): annihilate_flag = %d, want 1 (湮灭触发)",
			g.Counters[annihilateFlagID].Value)
	}

	// Case 2: target signature = Ousia (荒) + actor = Ousia (荒) → 同性不触发
	g.WriteCounter(detectionArkheID, engine.OpSet, 2) // Arkhe.Ousia
	g.WriteCounter(annihilateFlagID, engine.OpSet, 0)

	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPhysical, 1, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	if g.Counters[annihilateFlagID].Value != 0 {
		t.Errorf("Case 2 (Ousia attacker vs Ousia target): annihilate_flag = %d, want 0 (同性不触发)",
			g.Counters[annihilateFlagID].Value)
	}
}
