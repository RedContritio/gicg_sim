package tests

// v_phase2 事件卡 e2e — 走 production GetLegalActions / Step 真路径
// 验证每张卡运行时效果。断言数值从 data/cleaned/action/<id>_<name>.yaml
// effect_text 抽,不读 lua 实现(test 与 lua 同源会锁死 bug)。
//
// 覆盖卡:
//   5475 甜甜花酿鸡   cleaned: 治疗目标角色 1 点 / 饱腹 lock
//   5529 蒙德土豆饼   cleaned: 治疗目标角色 2 点 / 饱腹 lock
//   5480 最好的伙伴！ cleaned: 生成 2 个万能元素

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// foodCardE2EHeal 共享 setup:NewGameWithDeck → inject 卡 → 受伤 → 出卡 →
// 断言 HP delta + 饱腹=1 + 卡进 Discard。仅 wantHealDelta 不同。
func foodCardE2EHeal(t *testing.T, cardName string, wantHealDelta int, costSetup func(env *GameEnv)) {
	t.Helper()
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	card := env.RT.Cards.ByName[cardName]
	if card == nil {
		t.Fatalf("%s not in test pool", cardName)
	}
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})

	// P0 char 0(凯亚) HP=10 max,设 HP=8 为正常 baseline(留 +2 空间测最好的)
	hpCID := env.RT.Chars.BySlot[0][0].HPCounterID
	env.G.Counters[hpCID].Value = 8
	hpBefore := env.HP(0, 0)

	if costSetup != nil {
		costSetup(env)
	}

	idx := env.FindAction(engine.ActionCard, cardName)
	if idx < 0 {
		t.Fatalf("%s not offered after setup", cardName)
	}
	env.Step(idx)

	hpAfter := env.HP(0, 0)
	if hpAfter-hpBefore != wantHealDelta {
		t.Errorf("HP delta = %d, want +%d (cleaned ground truth: 治疗目标角色 %d 点)",
			hpAfter-hpBefore, wantHealDelta, wantHealDelta)
	}

	// 饱腹 = 1(PerChar scope,P0 char 0 IDs[0])
	baoFu, ok := env.RT.CounterEntries()["饱腹"]
	if !ok {
		t.Fatal("饱腹 counter not declared")
	}
	pc, _ := baoFu.Ref.(*interp.PerCharProxy)
	if got := env.G.Counters[pc.IDs[0]].Value; got != 1 {
		t.Errorf("饱腹(0,0) = %d, want 1 (after play)", got)
	}

	// 卡进 P0 Discard
	found := false
	for _, c := range env.G.Players[0].Discard {
		if c.Ref == card.Ref {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("%s ref %d not in P0 Discard after play", cardName, card.Ref)
	}
}

func foodCardE2EBlockedFull(t *testing.T, cardName string) {
	t.Helper()
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	card := env.RT.Cards.ByName[cardName]
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})

	// 饱腹=1 → 任何 own char 都被 lock
	baoFu, _ := env.RT.CounterEntries()["饱腹"]
	pc, _ := baoFu.Ref.(*interp.PerCharProxy)
	env.G.Counters[pc.IDs[0]].Value = 1

	if idx := env.FindAction(engine.ActionCard, cardName); idx >= 0 {
		t.Errorf("%s still offered with 饱腹=1, idx=%d (cleaned ground truth: 饱腹 lock)",
			cardName, idx)
	}
}

func TestEvent_甜甜花酿鸡_HealOwn1(t *testing.T) {
	// cleaned 5475: cost={} (0) / effect: 治疗目标角色 1 点
	foodCardE2EHeal(t, "甜甜花酿鸡", 1, nil) // 0 cost,no SetDice
}

func TestEvent_甜甜花酿鸡_BlockedWhenFull(t *testing.T) {
	foodCardE2EBlockedFull(t, "甜甜花酿鸡")
}

func TestEvent_蒙德土豆饼_HealOwn2(t *testing.T) {
	// cleaned 5529: cost={match:1} / effect: 治疗目标角色 2 点
	foodCardE2EHeal(t, "蒙德土豆饼", 2, func(env *GameEnv) {
		// match=1 同色 1 个 dice,任意 element 即可
		env.SetDice(0, map[int]int{int(engine.DiceColorFire): 1})
	})
}

func TestEvent_蒙德土豆饼_BlockedWhenFull(t *testing.T) {
	foodCardE2EBlockedFull(t, "蒙德土豆饼")
}

func TestEvent_最好的伙伴_GenOmni2(t *testing.T) {
	// cleaned 5480: cost={any:2} / effect: 生成 2 个万能元素
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	card := env.RT.Cards.ByName["最好的伙伴！"]
	if card == nil {
		t.Fatal("最好的伙伴！ not in test pool")
	}
	env.G.Players[0].Hand = append(env.G.Players[0].Hand, engine.CardInst{Ref: card.Ref})

	// SetDice 严格控制 dice 池:fire=2 满足 cost any=2,omni=0 baseline
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 2})

	omniCID := env.RT.DiceCounterID(0, int(engine.DiceColorOmni))
	fireCID := env.RT.DiceCounterID(0, int(engine.DiceColorFire))
	omniBefore := env.G.Counters[omniCID].Value
	fireBefore := env.G.Counters[fireCID].Value
	if omniBefore != 0 || fireBefore != 2 {
		t.Fatalf("setup dice omni=%d fire=%d, want 0 / 2", omniBefore, fireBefore)
	}

	idx := env.FindAction(engine.ActionCard, "最好的伙伴！")
	if idx < 0 {
		t.Fatal("最好的伙伴！ not offered with fire=2")
	}
	env.Step(idx)

	omniAfter := env.G.Counters[omniCID].Value
	fireAfter := env.G.Counters[fireCID].Value
	if omniAfter-omniBefore != 2 {
		t.Errorf("dice_omni delta = %d, want +2 (cleaned 5480: 生成 2 个万能元素)",
			omniAfter-omniBefore)
	}
	if fireAfter != 0 {
		t.Errorf("dice_fire after pay = %d, want 0 (cost any=2 consumed both fire)", fireAfter)
	}

	// 卡进 P0 Discard
	found := false
	for _, c := range env.G.Players[0].Discard {
		if c.Ref == card.Ref {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("最好的伙伴！ ref %d not in P0 Discard after play", card.Ref)
	}
}
