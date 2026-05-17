package tests

// v_phase2 池 — 7 张代表卡 (装备 2 + 事件 3 + 支援 2) 字段锁定 spike test。
//
// 锁定 data/pools/v_phase2/cards/*/*.lua 与
// data/cleaned/action/<id>_<name>.yaml 一致:
//   - cost (DiceCost.Specific + Match + Any + Energy)
//   - slot (None / Equip / Support)
//   - requires_weapon (装备牌)
// 简化机制 (talent buff / 条件 / 弃置等) deferred 不在锁范围。
//
// 7 张代表覆盖 3 子类:
//   装备牌:旅行剑 (单手剑) + 魔导绪论 (法器)
//   事件牌:甜甜花酿鸡 (0 cost 治 1) + 蒙德土豆饼 (1 同色 治 2)
//          + 最好的伙伴 (2 无色 生成 2 万能)
//   支援牌:派蒙 (3 同色 +万能) + 鸣神大社 (2 同色 技能 +万能)

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

type cardSpec struct {
	Name           string
	CostMatch      int
	CostAny        int
	Slot           interp.CardSlot
	RequiresWeapon int // 0 = no requirement
}

func TestVPhase2CardFieldLocks(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	_ = env.G

	cases := []cardSpec{
		// 装备牌
		{Name: "旅行剑", CostMatch: 2, Slot: interp.SlotNone, RequiresWeapon: 1 /*Sword*/},
		{Name: "魔导绪论", CostMatch: 2, Slot: interp.SlotNone, RequiresWeapon: 5 /*Catalyst*/},
		// 事件牌
		{Name: "甜甜花酿鸡", CostMatch: 0, Slot: interp.SlotNone, RequiresWeapon: 0},
		{Name: "蒙德土豆饼", CostMatch: 1, Slot: interp.SlotNone, RequiresWeapon: 0},
		{Name: "最好的伙伴！", CostAny: 2, Slot: interp.SlotNone, RequiresWeapon: 0},
		// 支援牌
		{Name: "派蒙", CostMatch: 3, Slot: interp.SlotSupport, RequiresWeapon: 0},
		{Name: "鸣神大社", CostMatch: 2, Slot: interp.SlotSupport, RequiresWeapon: 0},
	}

	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			card := env.RT.Cards.ByName[c.Name]
			if card == nil {
				t.Fatalf("card %q not in pool", c.Name)
			}
			wantCost := engine.Cost{Dices: engine.DiceCost{Match: c.CostMatch, Any: c.CostAny}}
			if card.Cost != wantCost {
				t.Errorf("cost: want %+v (cleaned 同色=%d 无色=%d), got %+v", wantCost, c.CostMatch, c.CostAny, card.Cost)
			}
			if card.Slot != c.Slot {
				t.Errorf("slot: want %d, got %d", c.Slot, card.Slot)
			}
			if card.RequiresWeapon != c.RequiresWeapon {
				t.Errorf("requires_weapon: want %d, got %d", c.RequiresWeapon, card.RequiresWeapon)
			}
		})
	}
}
