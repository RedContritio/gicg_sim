package tests

// TestObsEncoderB3cSpike — ADR-0019 §B.3c spike。
// 验证 BuildDynamicObs 加 recent_damage + prepare-skill 段后:
//   1. DynamicObsSize 反映新段 size 增长
//   2. 触发 1 damage 后 obs recent_damage 段含 typed event 字段
//   3. set_preparing 后 obs prepare-skill 段含 typed (char_idx, skill_slot)
//      不暴露 global skillID

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestObsEncoderB3cSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"歼灭机关"}, []string{"歼灭机关"})
	g := env.G

	// Test 1: DynamicObsSize 含新段
	expectedExtraSlots := engine.ObsRecentDamageSlots + engine.ObsPrepareSkillSlots
	if expectedExtraSlots != 88+4 {
		t.Errorf("expectedExtraSlots = %d, want 92 (88 damage + 4 prepare)", expectedExtraSlots)
	}

	// Build obs (initial state, ring 空, prepare 空)
	obs := g.BuildDynamicObs(0)
	if len(obs) != engine.DynamicObsSize() {
		t.Errorf("obs len = %d, want %d", len(obs), engine.DynamicObsSize())
	}

	// 计算 prepare-skill 段 offset。dyn obs 末尾顺序:
	//   recent_damage (88) → prepare_skill (4) → modifier_log (160)
	prepareOffset := engine.DynamicObsSize() - engine.ObsBuffSlots - engine.ObsModifierLogSlots - engine.ObsPrepareSkillSlots
	for i := 0; i < engine.ObsPrepareSkillSlots; i++ {
		if obs[prepareOffset+i] != -1 {
			t.Errorf("initial obs prepare[%d] = %d, want -1 (no prepare)",
				i, obs[prepareOffset+i])
		}
	}

	// Test 2: 触发 1 damage,验证 recent_damage 段
	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPhysical, 2, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	obs = g.BuildDynamicObs(0)
	damageOffset := engine.DynamicObsSize() - engine.ObsBuffSlots - engine.ObsModifierLogSlots - engine.ObsPrepareSkillSlots - engine.ObsRecentDamageSlots
	// event 0 字段:
	//   0 actor_player / 1 actor_char / 2 target_player / 3 target_char /
	//   4 element / 5 raw / 6 final / 7 absorbed / 8 is_piercing / 9 is_hit / 10 reaction_kind
	if obs[damageOffset+0] != 0 {
		t.Errorf("damage event[0].actor_player = %d, want 0", obs[damageOffset+0])
	}
	if obs[damageOffset+2] != 1 {
		t.Errorf("damage event[0].target_player = %d, want 1", obs[damageOffset+2])
	}
	if obs[damageOffset+4] != int32(engine.ElemPhysical) {
		t.Errorf("damage event[0].element = %d, want Physical (%d)",
			obs[damageOffset+4], engine.ElemPhysical)
	}
	if obs[damageOffset+5] < 1 {
		t.Errorf("damage event[0].raw_value = %d, want > 0", obs[damageOffset+5])
	}
	if obs[damageOffset+9] != 1 {
		t.Errorf("damage event[0].is_hit = %d, want 1", obs[damageOffset+9])
	}

	// Test 3: set_preparing 后 prepare-skill 段
	// 找一个 skill ID
	var skillID int
	for id, sk := range env.RT.Skills.ByID {
		if sk.Name == "高频旋击" {
			skillID = id
			break
		}
	}
	if skillID == 0 {
		t.Skip("高频旋击 skill not loaded")
	}

	g.Preparing[0] = skillID
	obs = g.BuildDynamicObs(0)

	// P0 prepare slot at offset prepareOffset+0 (char) + 1 (slot)
	gotChar := obs[prepareOffset+0]
	gotSlot := obs[prepareOffset+1]
	// 实际反查 (避免 hardcode 角色 char_idx,因为 char 加载顺序可能变)
	resolver := g.Extra.(engine.SkillIdentityResolver)
	expectedChar, expectedSlot, ok := resolver.SkillIdentityOf(0, skillID)
	if !ok {
		t.Skip("SkillIdentityOf 反查失败,跳过 prepare-skill 子测")
	}
	if int(gotChar) != expectedChar {
		t.Errorf("prepare char = %d, want %d", gotChar, expectedChar)
	}
	if int(gotSlot) != expectedSlot {
		t.Errorf("prepare slot = %d, want %d", gotSlot, expectedSlot)
	}
	// P1 仍无 prepare,应是 (-1, -1)
	if obs[prepareOffset+2] != -1 || obs[prepareOffset+3] != -1 {
		t.Errorf("P1 prepare = (%d, %d), want (-1, -1)",
			obs[prepareOffset+2], obs[prepareOffset+3])
	}
}
