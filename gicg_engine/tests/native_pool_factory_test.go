package tests

import (
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
)

func TestNativePoolAllStarterTriosCompileThroughProductionFactory(t *testing.T) {
	names := []string{"凯亚", "迪卢克", "芭芭拉", "砂糖", "菲谢尔"}
	common := []string{"甜甜花酿鸡", "蒙德土豆饼", "最好的伙伴！", "运筹帷幄", "换班时间",
		"交给我吧！", "莲花酥", "北地烟熏鸡", "烤蘑菇披萨", "兽肉薄荷卷", "星天之兆", "鹤归之时",
		"本大爷还没有输！", "派蒙", "鸣神大社"}
	deck := make([]string, 0, 30)
	for _, name := range common {
		deck = append(deck, name, name)
	}
	for i := 0; i < len(names); i++ {
		for j := i + 1; j < len(names); j++ {
			for k := j + 1; k < len(names); k++ {
				team := []string{names[i], names[j], names[k]}
				t.Run(strings.Join(team, "_"), func(t *testing.T) {
					cfg := factory.GameConfig{DataDir: dataDir, Pools: []string{"native_latest"}, Seed: 42}
					for p := range cfg.Players {
						for _, name := range team {
							cfg.Players[p].Chars = append(cfg.Players[p].Chars, factory.CharDef{Name: name})
						}
						cfg.Players[p].Deck = append([]string(nil), deck...)
					}
					h, err := factory.NewGame(cfg)
					if err != nil {
						t.Fatal(err)
					}
					h.Game.Step(0)
					h.Game.Step(0)
					h.Game.GetLegalActions()
					if len(h.Game.BuildStaticObs()) != engine.StaticObsSize() {
						t.Fatal("static observation size mismatch")
					}
					for p := 0; p < 2; p++ {
						if len(h.Game.BuildDynamicObs(p)) != engine.DynamicObsSize() {
							t.Fatal("dynamic observation size mismatch")
						}
						if len(h.Game.Players[p].Deck)+len(h.Game.Players[p].Hand) != 30 {
							t.Fatal("fixed thirty-card deck was not preserved")
						}
					}
				})
			}
		}
	}
}
