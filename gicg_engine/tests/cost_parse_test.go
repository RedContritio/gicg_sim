package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestSkillCostParse verifies that the declare_skill signature
// `declare_skill(char, name, cost_table)` correctly populates the
// Skill registry's Cost field with the expected DiceCost + Energy.
//
// We check every skill declared in the 5-character set:
//   - Normal attacks: 1 char-elem + 2 any
//   - Elemental skills: N char-elem
//   - Bursts: N char-elem + energy
func TestSkillCostParse(t *testing.T) {
	env := NewGameWithDeck(t,
		[]string{"赤蝶", "墨客", "猫咪"},
		[]string{"刻师傅", "天星", "赤蝶"},
	)

	expect := []struct {
		charName string
		name     string
		specific map[int]int // DiceColor index → count
		any      int
		energy   int
	}{
		// 赤蝶 (Fire)
		{"赤蝶", "枪", map[int]int{engine.DiceColorFire: 1}, 2, 0},
		{"赤蝶", "蝶火", map[int]int{engine.DiceColorFire: 3}, 0, 0},
		{"赤蝶", "回火", map[int]int{engine.DiceColorFire: 3}, 0, 3},
		// 墨客 (Water)
		{"墨客", "剑", map[int]int{engine.DiceColorWater: 1}, 2, 0},
		{"墨客", "墨意", map[int]int{engine.DiceColorWater: 2}, 0, 0},
		{"墨客", "水龙吟", map[int]int{engine.DiceColorWater: 3}, 0, 2},
		// 猫咪 (Ice)
		{"猫咪", "箭", map[int]int{engine.DiceColorIce: 1}, 2, 0},
		{"猫咪", "猫爪护盾", map[int]int{engine.DiceColorIce: 3}, 0, 0},
		{"猫咪", "甜美领域", map[int]int{engine.DiceColorIce: 3}, 0, 3},
		// 刻师傅 (Electro)
		{"刻师傅", "剑", map[int]int{engine.DiceColorElectro: 1}, 2, 0},
		{"刻师傅", "刻印", map[int]int{engine.DiceColorElectro: 3}, 0, 0},
		{"刻师傅", "雷暴", map[int]int{engine.DiceColorElectro: 3}, 0, 3},
		// 天星 (Geo)
		{"天星", "枪", map[int]int{engine.DiceColorGeo: 1}, 2, 0},
		{"天星", "岩脊", map[int]int{engine.DiceColorGeo: 3}, 0, 0},
		{"天星", "玉璋", map[int]int{engine.DiceColorGeo: 5}, 0, 0},
		{"天星", "天星", map[int]int{engine.DiceColorGeo: 3}, 0, 3},
	}

	for _, e := range expect {
		// Find skill by (char_name, skill_name) — names collide across
		// characters (e.g. "枪" is both 赤蝶's Fire-based and 天星's
		// Geo-based basic attack).
		var cost engine.Cost
		found := false
		for _, s := range env.RT.Skills.ByID {
			if s.Name == e.name && s.CharName == e.charName {
				cost = s.Cost
				found = true
				break
			}
		}
		if !found {
			t.Errorf("skill %s/%q not found in registry", e.charName, e.name)
			continue
		}

		// Check specific counts
		for color, want := range e.specific {
			got := cost.Dices.Specific[color]
			if got != want {
				t.Errorf("skill %q: Specific[%d] = %d, want %d",
					e.name, color, got, want)
			}
		}
		// Check that no other specific colors are set
		for i := 0; i < 7; i++ {
			if _, expected := e.specific[i]; expected {
				continue
			}
			if cost.Dices.Specific[i] != 0 {
				t.Errorf("skill %q: unexpected Specific[%d] = %d",
					e.name, i, cost.Dices.Specific[i])
			}
		}
		if cost.Dices.Any != e.any {
			t.Errorf("skill %q: Any = %d, want %d",
				e.name, cost.Dices.Any, e.any)
		}
		if cost.Dices.Match != 0 {
			t.Errorf("skill %q: Match = %d, want 0", e.name, cost.Dices.Match)
		}
		if cost.Energy != e.energy {
			t.Errorf("skill %q: Energy = %d, want %d",
				e.name, cost.Energy, e.energy)
		}
	}
}

// TestCardCostParse verifies every card declaration correctly parses
// its `{ dices = {...}, energy = N }` cost table into the expected
// DiceCost + energy.
func TestCardCostParse(t *testing.T) {
	env := NewGameWithDeck(t,
		[]string{"赤蝶", "墨客", "猫咪"},
		[]string{"刻师傅", "天星", "赤蝶"},
	)

	type want struct {
		anyN    int
		fire    int
		ice     int
		water   int
		electro int
		geo     int
		energy  int
	}
	// Most cards use only any-count; talent cards use specific
	// element + (for ult talents) energy.
	expect := map[string]want{
		"碌碌无为": {anyN: 1},
		"佛跳墙":  {anyN: 2},
		"美味烧鸡": {anyN: 1},
		"占星":   {anyN: 2},
		"诅咒":   {anyN: 2},
		"反制":   {anyN: 2},
		"荷花酥":  {anyN: 2},
		"速速茶点": {anyN: 1},
		"铁剑":   {anyN: 2},
		"铁枪":   {anyN: 2},
		"以牙还牙": {anyN: 2},
		"伏兵之术": {anyN: 2},
		"清洁时间": {anyN: 3},
		"瞬身之术": {anyN: 2},
		"铁弓":   {anyN: 2},
		"西风剑":  {anyN: 3},
		"西风长枪": {anyN: 3},
		"玄冰":   {anyN: 1},
		"乘胜追击": {anyN: 4},
		"以攻代守": {anyN: 4},
		"以逸待劳": {anyN: 8},
		"复刻":   {electro: 3}, // matches 刻印 cost
		// Talent cards: specific element + optional energy.
		"蝶鳞":   {fire: 3},
		"刺刺猫爪": {ice: 3},
		"发现静电": {electro: 3},
		"星愿":   {geo: 5},
		"守正":   {water: 3, energy: 2},
	}

	colorIdx := map[string]int{
		"fire":    0,
		"ice":     1,
		"water":   2,
		"electro": 3,
		"geo":     4,
	}
	for name, w := range expect {
		entry, ok := env.RT.Cards.ByName[name]
		if !ok {
			t.Logf("card %q not loaded in this test env; skipping", name)
			continue
		}
		if entry.Cost.Dices.Any != w.anyN {
			t.Errorf("card %q: Any = %d, want %d",
				name, entry.Cost.Dices.Any, w.anyN)
		}
		wantSpecific := [7]int{}
		wantSpecific[colorIdx["fire"]] = w.fire
		wantSpecific[colorIdx["ice"]] = w.ice
		wantSpecific[colorIdx["water"]] = w.water
		wantSpecific[colorIdx["electro"]] = w.electro
		wantSpecific[colorIdx["geo"]] = w.geo
		for i := 0; i < 7; i++ {
			if entry.Cost.Dices.Specific[i] != wantSpecific[i] {
				t.Errorf("card %q: Specific[%d] = %d, want %d",
					name, i, entry.Cost.Dices.Specific[i], wantSpecific[i])
			}
		}
		if entry.Cost.Dices.Match != 0 {
			t.Errorf("card %q: Match = %d, want 0", name, entry.Cost.Dices.Match)
		}
		if entry.Cost.Energy != w.energy {
			t.Errorf("card %q: Energy = %d, want %d",
				name, entry.Cost.Energy, w.energy)
		}
	}
}
