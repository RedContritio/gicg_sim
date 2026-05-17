package tests

// v_phase2 装备卡 e2e — 走 production GetLegalActions / Step 真路径
// 验证装备生效路径 + 反面验证(不装则不 +1, 装在角色 A 不影响角色 B)。
// 数值断言从 data/cleaned/action/<id>_<name>.yaml 抽,不读 lua。
//
// 覆盖:
//   5418 旅行剑   cleaned: 角色造成的伤害+1 / 装备者「单手剑」
//   5406 魔导绪论 cleaned: 角色造成的伤害+1 / 装备者「法器」
//
// Test 方法:A baseline(不装)vs B with-equip(同 setup 出装备后用 skill),
// 对比 enemy HP delta = damage delta。yaml "角色造成的伤害+1" → delta=+1。
//
// Note(已 acknowledge 在 plan):lua 当前 on_damage_add 限定 ctx.source ==
// Source.Skill,只对 skill 伤害 +1,不覆盖 reaction / card / summon source。
// 严格按 yaml 应所有"角色造成"伤害 +1,但 v_phase2 无召唤物 / damage 事件牌
// fixture,且反应伤害需复杂元素附着 setup → defer 非 skill source 反面测试。
// 当前 happy 覆盖 skill type ≥2(普攻 + 元素战技)证明不限 normal attack。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// damageWithSkill 让 (charP=charC=0) 用 skillName 攻击 P1 active char。
// 返回 P1 active char (=1, idx 0) HP delta 作为 damage。caller 必须先 SetDice
// 满足 skill cost,装备(若有)必须先于此调用挂上。返回 -1 if skill not playable。
func damageWithSkill(env *GameEnv, skillName string) int {
	defenderHpCID := env.RT.Chars.BySlot[1][0].HPCounterID
	hpBefore := env.G.Counters[defenderHpCID].Value
	if !env.StepSkill(skillName) {
		return -1
	}
	hpAfter := env.G.Counters[defenderHpCID].Value
	return hpBefore - hpAfter
}

// equipCardAB 共享 setup:fresh env + 可选 inject 装备牌并播放(target self),
// 然后 SetDice + 用 skill 打 P1。返回 damage。equipCard 为空字符串则不装。
func equipCardAB(t *testing.T, charP0 string, equipCardName string, equipCost map[int]int, skillName string, skillCost map[int]int) int {
	t.Helper()
	env := NewGameWithDeck(t, []string{charP0}, []string{"克洛琳德"})
	if equipCardName != "" {
		equip := env.RT.Cards.ByName[equipCardName]
		if equip == nil {
			t.Fatalf("%s not in test pool", equipCardName)
		}
		env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: equip.Ref})
		env.SetDice(0, equipCost)
		idx := env.FindAction(engine.ActionCard, equipCardName)
		if idx < 0 {
			t.Fatalf("%s not offered for %s (weapon mismatch?)", equipCardName, charP0)
		}
		env.Step(idx)
	}
	env.SetDice(0, skillCost)
	dmg := damageWithSkill(env, skillName)
	if dmg < 0 {
		t.Fatalf("skill %s not playable (charP0=%s equipped=%q dice=%d)",
			skillName, charP0, equipCardName, env.DiceTotal(0))
	}
	return dmg
}

func TestEquip_旅行剑_DamageDeltaAnySkillType(t *testing.T) {
	// cleaned 5418: cost match=2 / "角色造成的伤害+1"(任意 skill type)
	// 凯亚 weapon=Sword 满足装备条件

	t.Run("NormalAttack", func(t *testing.T) {
		// 仪典剑术 cost ice 1 + any 2 = 3 dice
		skillCost := map[int]int{int(engine.DiceColorIce): 3}
		baseline := equipCardAB(t, "凯亚", "", nil, "仪典剑术", skillCost)
		withEquip := equipCardAB(t, "凯亚",
			"旅行剑", map[int]int{int(engine.DiceColorFire): 2}, "仪典剑术", skillCost)
		if withEquip-baseline != 1 {
			t.Errorf("普攻 damage delta = %d (baseline=%d, equipped=%d), want +1 (cleaned 5418: 角色造成的伤害+1)",
				withEquip-baseline, baseline, withEquip)
		}
	})

	t.Run("ElementalSkill", func(t *testing.T) {
		// 霜袭 cost ice 3
		skillCost := map[int]int{int(engine.DiceColorIce): 3}
		baseline := equipCardAB(t, "凯亚", "", nil, "霜袭", skillCost)
		withEquip := equipCardAB(t, "凯亚",
			"旅行剑", map[int]int{int(engine.DiceColorFire): 2}, "霜袭", skillCost)
		if withEquip-baseline != 1 {
			t.Errorf("元素战技 damage delta = %d, want +1 (cleaned 5418: 任意 skill type 不限)",
				withEquip-baseline)
		}
	})
}

func TestEquip_旅行剑_NotLeakToTeammate(t *testing.T) {
	// P0=[凯亚 装旅行剑, 凝光 不装]。凝光 用千金掷 打 P1 → 凝光不是装备者,
	// damage 不该 +1。
	skillCost := map[int]int{int(engine.DiceColorGeo): 3}
	// A baseline:无人装备,凝光打
	baselineEnv := NewGameWithDeck(t, []string{"凯亚", "凝光"}, []string{"克洛琳德"})
	// 切到凝光(active 改为 1)
	baselineEnv.G.Players[0].ActiveChar = 1
	baselineEnv.SetDice(0, skillCost)
	baseline := damageWithSkill(baselineEnv, "千金掷")
	if baseline < 0 {
		t.Fatal("baseline 千金掷 not playable")
	}

	// B with-equip:凯亚 装旅行剑(target=凯亚=char 0),然后切凝光打
	env := NewGameWithDeck(t, []string{"凯亚", "凝光"}, []string{"克洛琳德"})
	equip := env.RT.Cards.ByName["旅行剑"]
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: equip.Ref})
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 2})
	idx := env.FindAction(engine.ActionCard, "旅行剑")
	if idx < 0 {
		t.Fatal("旅行剑 not offered (P0 active=凯亚 should satisfy Sword)")
	}
	env.Step(idx) // 装在 active=凯亚 (char 0)
	env.G.Players[0].ActiveChar = 1
	env.SetDice(0, skillCost)
	withEquip := damageWithSkill(env, "千金掷")
	if withEquip < 0 {
		t.Fatal("with-equip 千金掷 not playable")
	}

	// 凝光 不是装备者 → damage 不 +1
	if withEquip != baseline {
		t.Errorf("凝光 damage (baseline=%d, 凯亚装剑=%d): delta=%d, want 0 — "+
			"yaml 5418 只 buff 装备者(凯亚),不该 leak to teammate 凝光",
			baseline, withEquip, withEquip-baseline)
	}
}

func TestEquip_旅行剑_BlockedNonSword(t *testing.T) {
	// 凝光 weapon=Catalyst,active 时旅行剑 target check 拒绝
	env := NewGameWithDeck(t, []string{"凝光"}, []string{"克洛琳德"})
	card := env.RT.Cards.ByName["旅行剑"]
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 2})
	if idx := env.FindAction(engine.ActionCard, "旅行剑"); idx >= 0 {
		t.Errorf("旅行剑 offered with active=凝光 (Catalyst),idx=%d "+
			"(cleaned 5418: requires_weapon=单手剑)", idx)
	}
}

func TestEquip_魔导绪论_DamageDeltaAnySkillType(t *testing.T) {
	// cleaned 5406: cost match=2 / "角色造成的伤害+1" / 装备者「法器」

	t.Run("NormalAttack", func(t *testing.T) {
		// 千金掷 cost geo 1 + any 2 = 3 dice
		skillCost := map[int]int{int(engine.DiceColorGeo): 3}
		baseline := equipCardAB(t, "凝光", "", nil, "千金掷", skillCost)
		withEquip := equipCardAB(t, "凝光",
			"魔导绪论", map[int]int{int(engine.DiceColorFire): 2}, "千金掷", skillCost)
		if withEquip-baseline != 1 {
			t.Errorf("普攻 damage delta = %d (baseline=%d, equipped=%d), want +1",
				withEquip-baseline, baseline, withEquip)
		}
	})

	t.Run("ElementalSkill", func(t *testing.T) {
		// 璇玑屏 cost geo 3
		skillCost := map[int]int{int(engine.DiceColorGeo): 3}
		baseline := equipCardAB(t, "凝光", "", nil, "璇玑屏", skillCost)
		withEquip := equipCardAB(t, "凝光",
			"魔导绪论", map[int]int{int(engine.DiceColorFire): 2}, "璇玑屏", skillCost)
		if withEquip-baseline != 1 {
			t.Errorf("元素战技 damage delta = %d, want +1", withEquip-baseline)
		}
	})
}

func TestEquip_魔导绪论_BlockedNonCatalyst(t *testing.T) {
	// 凯亚 weapon=Sword,active 时魔导绪论 target check 拒绝
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	card := env.RT.Cards.ByName["魔导绪论"]
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 2})
	if idx := env.FindAction(engine.ActionCard, "魔导绪论"); idx >= 0 {
		t.Errorf("魔导绪论 offered with active=凯亚 (Sword),idx=%d "+
			"(cleaned 5406: requires_weapon=法器)", idx)
	}
}
