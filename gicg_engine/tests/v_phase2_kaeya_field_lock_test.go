package tests

// v_phase2 池 — 7 张 character 字段锁定 spike test。
//
// 锁定 data/pools/v_phase2/characters/*/*.lua 与
// data/cleaned/character/<id>_<name>.yaml 一致:
//   - HP / energy / element
//   - 每个 skill 的 cost (DiceCost.Specific + Any + Energy)
//   - skill 名严格对照 cleaned (无多余 / 无缺失)
//   - 简化机制 (status / summon / 条件 buff) deferred 不在锁范围
//
// 任何 lua 改动偏离 cleaned 数值 → 此 test fail,提示 source 锁失效。
//
// 7 元素覆盖: 火-玛薇卡 / 水-坎蒂丝 / 雷-克洛琳德 / 草-柯莱 /
//             冰-凯亚 / 岩-凝光 / 风-砂糖

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

type skillSpec struct {
	Name string
	Cost engine.Cost
}

type charSpec struct {
	Name     string
	HP       int
	Energy   int
	Element  engine.Element
	Skills   []skillSpec
	Opponent string // 对手 char 名,用于 NewGameWithDeck
}

func cost(ice, fire, water, electro, geo, anemo, dendro, any, energy int) engine.Cost {
	c := engine.Cost{Energy: energy}
	c.Dices.Any = any
	c.Dices.Specific[engine.DiceColorFire] = fire
	c.Dices.Specific[engine.DiceColorIce] = ice
	c.Dices.Specific[engine.DiceColorWater] = water
	c.Dices.Specific[engine.DiceColorElectro] = electro
	c.Dices.Specific[engine.DiceColorGeo] = geo
	c.Dices.Specific[engine.DiceColorAnemo] = anemo
	c.Dices.Specific[engine.DiceColorDendro] = dendro
	return c
}

func TestVPhase2CharFieldLocks(t *testing.T) {
	cases := []charSpec{
		{
			Name: "凯亚", HP: 10, Energy: 2, Element: engine.ElemIce,
			Opponent: "克洛琳德",
			Skills: []skillSpec{
				{"仪典剑术", cost(1, 0, 0, 0, 0, 0, 0, 2, 0)},
				{"霜袭", cost(3, 0, 0, 0, 0, 0, 0, 0, 0)},
				{"凛冽轮舞", cost(4, 0, 0, 0, 0, 0, 0, 0, 2)},
			},
		},
		{
			Name: "凝光", HP: 10, Energy: 3, Element: engine.ElemGeo,
			Opponent: "克洛琳德",
			Skills: []skillSpec{
				{"千金掷", cost(0, 0, 0, 0, 1, 0, 0, 2, 0)},
				{"璇玑屏", cost(0, 0, 0, 0, 3, 0, 0, 0, 0)},
				{"天权崩玉", cost(0, 0, 0, 0, 3, 0, 0, 0, 3)},
			},
		},
		{
			Name: "坎蒂丝", HP: 11, Energy: 2, Element: engine.ElemWater,
			Opponent: "克洛琳德",
			Skills: []skillSpec{
				{"流耀枪术·守势", cost(0, 0, 1, 0, 0, 0, 0, 2, 0)},
				{"圣仪·苍鹭庇卫", cost(0, 0, 3, 0, 0, 0, 0, 0, 0)},
				{"圣仪·灰鸰衒潮", cost(0, 0, 3, 0, 0, 0, 0, 0, 2)},
			},
		},
		{
			Name: "砂糖", HP: 10, Energy: 2, Element: engine.ElemAnemo,
			Opponent: "克洛琳德",
			Skills: []skillSpec{
				{"简式风灵作成", cost(0, 0, 0, 0, 0, 1, 0, 2, 0)},
				{"风灵作成·陆参零捌", cost(0, 0, 0, 0, 0, 3, 0, 0, 0)},
				{"禁·风灵作成·柒伍同构贰型", cost(0, 0, 0, 0, 0, 3, 0, 0, 2)},
			},
		},
		{
			Name: "柯莱", HP: 11, Energy: 2, Element: engine.ElemDendro,
			Opponent: "克洛琳德",
			Skills: []skillSpec{
				{"祈颂射艺", cost(0, 0, 0, 0, 0, 0, 1, 2, 0)},
				{"拂花偈叶", cost(0, 0, 0, 0, 0, 0, 3, 0, 0)},
				{"猫猫秘宝", cost(0, 0, 0, 0, 0, 0, 3, 0, 2)},
			},
		},
		{
			Name: "克洛琳德", HP: 10, Energy: 2, Element: engine.ElemElectro,
			Opponent: "凯亚",
			Skills: []skillSpec{
				{"逐影之誓", cost(0, 0, 0, 1, 0, 0, 0, 2, 0)},
				{"狩夜之巡", cost(0, 0, 0, 2, 0, 0, 0, 0, 0)},
				{"残光将终", cost(0, 0, 0, 3, 0, 0, 0, 0, 2)},
			},
		},
		{
			Name: "玛薇卡", HP: 10, Energy: 3, Element: engine.ElemFire,
			Opponent: "克洛琳德",
			Skills: []skillSpec{
				{"以火织命", cost(0, 1, 0, 0, 0, 0, 0, 2, 0)},
				{"称名之刻", cost(0, 3, 0, 0, 0, 0, 0, 0, 0)},
				{"燔天之时", cost(0, 4, 0, 0, 0, 0, 0, 0, 3)},
			},
		},
	}

	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			env := NewGameWithDeck(t, []string{c.Name}, []string{c.Opponent})
			g := env.G

			ch := env.RT.Chars.BySlot[0][0]
			if ch.Name != c.Name {
				t.Fatalf("char binding: want %q got %q", c.Name, ch.Name)
			}
			if hpMax := g.Counters[ch.HPCounterID].Max; hpMax != c.HP {
				t.Errorf("HP max: want %d (cleaned), got %d", c.HP, hpMax)
			}
			if enMax := g.Counters[ch.EnergyCounterID].Max; enMax != c.Energy {
				t.Errorf("energy max: want %d (cleaned), got %d", c.Energy, enMax)
			}
			if engine.Element(ch.Element) != c.Element {
				t.Errorf("element: want %d (cleaned), got %d", c.Element, ch.Element)
			}

			expected := make(map[string]engine.Cost, len(c.Skills))
			for _, s := range c.Skills {
				expected[s.Name] = s.Cost
			}
			found := make(map[string]bool, len(c.Skills))
			for _, sid := range ch.SkillIDs {
				sk := env.RT.Skills.ByID[sid]
				want, ok := expected[sk.Name]
				if !ok {
					t.Errorf("unexpected skill %q (cleaned 仅 %d 主动)", sk.Name, len(c.Skills))
					continue
				}
				found[sk.Name] = true
				if sk.Cost != want {
					t.Errorf("skill %q cost: want %+v (cleaned), got %+v", sk.Name, want, sk.Cost)
				}
			}
			for name := range expected {
				if !found[name] {
					t.Errorf("skill missing: %q (cleaned)", name)
				}
			}
		})
	}
}
