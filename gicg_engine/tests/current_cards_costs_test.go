package tests

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

// Independent, explicit declaration ledger for the union of live-config decks
// plus DMC's padding card. These are project rules, not official-game card data.
func TestCurrentCards_DeclarationLedger(t *testing.T) {
	e := currentCardGame(t, 0)
	anyCosts := map[string]int{
		"乘胜追击": 4, "以攻代守": 4, "以牙还牙": 2, "伏兵之术": 2, "佛跳墙": 2,
		"占星": 2, "反制": 2, "清洁时间": 3, "玄冰": 1, "瞬身之术": 2, "美味烧鸡": 1,
		"荷花酥": 2, "西风剑": 3, "西风长枪": 3, "诅咒": 2, "测试卡_碎片": 1, "碌碌无为": 1,
	}
	expected := map[string]engine.Cost{}
	for name, n := range anyCosts {
		expected[name] = engine.Cost{Dices: engine.DiceCost{Any: n}}
	}
	for _, name := range []string{"测试卡_增幅", "测试卡_神秘水流"} {
		expected[name] = engine.Cost{Dices: engine.DiceCost{Match: 2}}
	}
	c := engine.Cost{}
	c.Dices.Specific[engine.DiceColorFire] = 3
	expected["蝶鳞"] = c
	c = engine.Cost{Energy: 2}
	c.Dices.Specific[engine.DiceColorWater] = 3
	expected["守正"] = c
	for name, want := range expected {
		t.Run(name, func(t *testing.T) {
			card := e.RT.Cards.ByName[name]
			if card == nil {
				t.Fatal("live-config card missing")
			}
			if card.Cost != want {
				t.Fatalf("cost=%+v want %+v", card.Cost, want)
			}
			battle := name == "蝶鳞" || name == "守正"
			if card.BattleAction != battle {
				t.Fatalf("battle_action=%t want %t", card.BattleAction, battle)
			}
		})
	}
}
