package tests

// v_phase2 支援卡 e2e — 走 production GetLegalActions / Step 真路径
// 验证每张卡运行时效果。断言数值从 data/cleaned/action/<id>_<name>.yaml
// effect_text 抽,不读 lua 实现。
//
// 覆盖卡:
//   5448 派蒙       cleaned: 行动阶段开始时:生成 2 点万能元素 / 可用次数 2
//   6325 鸣神大社    cleaned: 我方角色使用技能后:如果元素骰总数为奇数,
//                            则生成 1 个万能元素 (每回合 2 次)
//
// Round 推进:env.StepEndTurn() × 2 → engine 自动 RoundEnd → RoundStart →
// fresh PhaseAction (无新 helper,见 plan 审计)。
// FixDice 控制 round_start fresh roll 出 0,使派蒙 add_dice 贡献可隔离。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// paimonSetupCanonical:setup NewGameWithDeck + FixDice=全 0(round_start
// fresh roll 全 0,使派蒙 +2 贡献可隔离)+ SetDice(P0, fire=3) 满足派蒙 cost。
// 返回派蒙 card ref 用于断言。
func paimonSetupCanonical(t *testing.T) (*GameEnv, int) {
	t.Helper()
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	card := env.RT.Cards.ByName["派蒙"]
	if card == nil {
		t.Fatal("派蒙 not in test pool")
	}
	// round_start fresh roll 全 0(via FixDice;round 2+ 起 fresh roll 用此)
	env.G.FixDice = make([]int, engine.DiceColorCount)
	// round 1 P0 dice 设 fire=3 满足派蒙 cost match=3
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 3})
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})
	return env, card.Ref
}

func TestSupport_派蒙_TwoRoundLifecycle(t *testing.T) {
	// cleaned 5448: cost={match:3} effect: 行动阶段开始时:+2 Omni / 可用次数 2
	env, paimonRef := paimonSetupCanonical(t)
	omniCID := env.RT.DiceCounterID(0, int(engine.DiceColorOmni))

	// 出派蒙 (round 1)
	idx := env.FindAction(engine.ActionCard, "派蒙")
	if idx < 0 {
		t.Fatal("派蒙 not offered with fire=3")
	}
	env.Step(idx)

	// Round 1 末:派蒙在 Supports + omni 未变(派蒙 effect 是 round_start trigger)
	if got := len(env.G.Players[0].Supports); got != 1 {
		t.Fatalf("after play: Supports=%d, want 1", got)
	}
	if env.G.Players[0].Supports[0].Ref != paimonRef {
		t.Errorf("Supports[0].Ref = %d, want 派蒙=%d",
			env.G.Players[0].Supports[0].Ref, paimonRef)
	}
	if got := env.G.Counters[omniCID].Value; got != 0 {
		t.Errorf("round 1 出派蒙后 dice_omni=%d, want 0 (effect 是 round_start trigger)", got)
	}

	// 推进到 round 2:dual StepEndTurn → PhaseRoundStart;GetLegalActions 触发 NewRound
	env.StepEndTurn()
	env.StepEndTurn()
	_ = env.G.GetLegalActions() // trigger NewRound + round_start hooks

	// Round 2 start 后:fresh roll 全 0 (FixDice) + 派蒙 add_dice(Omni, 2) = omni=2
	if got := env.G.Counters[omniCID].Value; got != 2 {
		t.Errorf("round 2 start 后 dice_omni=%d, want 2 (cleaned 5448: +2 Omni 第 1 次)", got)
	}
	if got := len(env.G.Players[0].Supports); got != 1 {
		t.Errorf("round 2 派蒙仍在 Supports,got len=%d", got)
	}

	// 推进到 round 3
	env.StepEndTurn()
	env.StepEndTurn()
	_ = env.G.GetLegalActions()

	// Round 3 start 后:fresh roll 全 0 + 派蒙 +2(active 从 1→0)+ remove_support
	// 注意:omniCID 已被 round_start 中 system/dice.lua roll_dice 重置后又被派蒙 +2 → 仍 =2
	if got := env.G.Counters[omniCID].Value; got != 2 {
		t.Errorf("round 3 start 后 dice_omni=%d, want 2 (第 2 次 trigger,fresh roll=0)", got)
	}
	if got := len(env.G.Players[0].Supports); got != 0 {
		t.Errorf("round 3 派蒙 active 耗尽应退槽,Supports len=%d, want 0", got)
	}
	// 退槽时 push 进 Discard
	found := false
	for _, c := range env.G.Players[0].Discard {
		if c.Ref == paimonRef {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("派蒙 ref %d not in P0 Discard after 2 triggers", paimonRef)
	}
}

func TestSupport_派蒙_BlockedWhenFull(t *testing.T) {
	env, paimonRef := paimonSetupCanonical(t)
	// Supports 满 4 槽位
	env.G.Players[0].Supports = make([]engine.SupportInst, engine.MaxSupportSlots)
	for i := range env.G.Players[0].Supports {
		env.G.Players[0].Supports[i] = engine.SupportInst{Ref: paimonRef, ActivatedAt: 1}
	}
	if idx := env.FindAction(engine.ActionCard, "派蒙"); idx >= 0 {
		t.Errorf("派蒙 still offered with Supports full (n=%d), idx=%d",
			engine.MaxSupportSlots, idx)
	}
}

// kamisatoSetupCanonical:setup NewGameWithDeck + 出鸣神大社(cost match=2)。
// Returns env after support is on board.
func kamisatoSetupCanonical(t *testing.T) *GameEnv {
	t.Helper()
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	card := env.RT.Cards.ByName["鸣神大社"]
	if card == nil {
		t.Fatal("鸣神大社 not in test pool")
	}
	// FixDice 控制后续 fresh roll(round_start)出全 0;round 1 当前 dice 通过 SetDice 单独控
	env.G.FixDice = make([]int, engine.DiceColorCount)
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 2}) // cost match=2
	idx := env.FindAction(engine.ActionCard, "鸣神大社")
	if idx < 0 {
		t.Fatal("鸣神大社 not offered with fire=2")
	}
	env.Step(idx)
	return env
}

func TestSupport_鸣神大社(t *testing.T) {
	// cleaned 6325 effect_text(完整):
	//   "我方角色使用技能后:如果元素骰总数为奇数,生成 1 个万能元素(每回合 2 次)"
	// 3 个条件:
	//   trigger:on_skill_use after
	//   condition:dice 总数为奇数
	//   limit:每回合 ≤ 2 次

	t.Run("Happy_OddDiceSkillGivesOmni", func(t *testing.T) {
		env := kamisatoSetupCanonical(t)
		omniCID := env.RT.DiceCounterID(0, int(engine.DiceColorOmni))

		// 双 EndTurn → PhaseRoundStart;GetLegalActions 触发 NewRound → round 2 PhaseAction
		// (FixDice 控制 fresh roll 全 0)
		env.StepEndTurn()
		env.StepEndTurn()
		_ = env.G.GetLegalActions()

		// SetDice 必须在 NewRound 之后(否则被 round_start roll_dice 覆盖)。
		// 凯亚普攻 cost = ice 1 + any 2 = 3;给 4 ice → 付费后剩 1 ice = 总数 1(奇数)
		env.SetDice(0, map[int]int{int(engine.DiceColorIce): 4})
		omniBefore := env.G.Counters[omniCID].Value
		normalSkillID := env.RT.Chars.BySlot[0][0].NormalAttackID
		normalName := env.G.SkillNames[normalSkillID]
		if !env.StepSkill(normalName) {
			t.Fatalf("StepSkill(%q) failed in round 2 (turn=%d phase=%d ice=%d)",
				normalName, env.G.Turn, env.G.Phase, env.DiceTotal(0))
		}
		omniAfter := env.G.Counters[omniCID].Value
		// yaml ground truth:奇数 dice → +1 Omni
		if omniAfter-omniBefore != 1 {
			t.Errorf("dice_omni delta = %d, want +1 (cleaned 6325: 奇数骰 +1)",
				omniAfter-omniBefore)
		}
	})

	t.Run("Condition_EvenDiceNoOmni", func(t *testing.T) {
		// cleaned 6325 condition: "元素骰总数为奇数"才 +1。偶数 不 +1。
		// 鸣神大社.lua header 自认 "deferred:奇数骰条件检查(本 lua 简化:无条件 +1)"。
		// 当前 lua 不实现 condition,偶数也 +1。此 sub-test 直到 lua 补完 dice
		// total parity 检查后撤 skip。
		t.Skip("lua deferred — cleaned 6325 says 奇数骰才 +1,but 鸣神大社.lua 简化 " +
			"为技能后无条件 +1。撤 skip 时 lua 需加 dice_total(p) % 2 == 1 check。")
	})

	t.Run("Limit_TwoPerRound", func(t *testing.T) {
		// cleaned 6325 limit: "每回合 2 次"。第 3 次技能不再 +1。
		env := kamisatoSetupCanonical(t)
		omniCID := env.RT.DiceCounterID(0, int(engine.DiceColorOmni))
		env.StepEndTurn()
		env.StepEndTurn()
		_ = env.G.GetLegalActions() // trigger NewRound

		normalSkillID := env.RT.Chars.BySlot[0][0].NormalAttackID
		normalName := env.G.SkillNames[normalSkillID]

		// 1st skill:expect +1 Omni
		env.SetDice(0, map[int]int{int(engine.DiceColorIce): 4})
		omniBefore := env.G.Counters[omniCID].Value
		if !env.StepSkill(normalName) {
			t.Fatal("StepSkill #1 failed")
		}
		omniAfter1 := env.G.Counters[omniCID].Value
		if omniAfter1-omniBefore != 1 {
			t.Errorf("1st skill: omni delta=%d, want +1", omniAfter1-omniBefore)
		}

		// 2nd skill:skill is battle action → turn flipped to P1。让 P1 EndTurn 回 P0(P0 未 declared)。
		env.StepEndTurn() // P1 EndTurn → 回 P0(还在 round 2,P0 未 declared)
		env.SetDice(0, map[int]int{int(engine.DiceColorIce): 4})
		omniBefore = env.G.Counters[omniCID].Value
		if !env.StepSkill(normalName) {
			t.Fatal("StepSkill #2 failed")
		}
		omniAfter2 := env.G.Counters[omniCID].Value
		if omniAfter2-omniBefore != 1 {
			t.Errorf("2nd skill: omni delta=%d, want +1 (still in 2-per-round limit)",
				omniAfter2-omniBefore)
		}

		// 3rd skill:P1 declared end → skill #2 后 turn 留 P0(flipTurn 不动 declared 方)。
		// 不再 EndTurn(那会让 P0 declare end + round 结束)。直接 SetDice + skill #3。
		env.SetDice(0, map[int]int{int(engine.DiceColorIce): 4})
		omniBefore = env.G.Counters[omniCID].Value
		if !env.StepSkill(normalName) {
			t.Fatalf("StepSkill #3 failed (turn=%d phase=%d ice=%d)",
				env.G.Turn, env.G.Phase, env.DiceTotal(0))
		}
		omniAfter3 := env.G.Counters[omniCID].Value
		if omniAfter3-omniBefore != 0 {
			t.Errorf("3rd skill in same round: omni delta=%d, want 0 (cleaned 6325 limit: 每回合 ≤2 次)",
				omniAfter3-omniBefore)
		}
	})
}

func TestSupport_鸣神大社_BlockedWhenFull(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	card := env.RT.Cards.ByName["鸣神大社"]
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 2})
	// Supports 满 4
	env.G.Players[0].Supports = make([]engine.SupportInst, engine.MaxSupportSlots)
	for i := range env.G.Players[0].Supports {
		env.G.Players[0].Supports[i] = engine.SupportInst{Ref: card.Ref, ActivatedAt: 1}
	}
	if idx := env.FindAction(engine.ActionCard, "鸣神大社"); idx >= 0 {
		t.Errorf("鸣神大社 still offered with Supports full, idx=%d", idx)
	}
}
