// interp_share_bench_test.go — profile how much of Game.GetLegalActions/Step
// wall time is DSL interpretation (interp package) vs engine core.
// 09-19: quantifies the "compile the fixed ruleset" upside.
//
// 跑法:
//
//	go test -bench=BenchmarkInterpShare -benchtime=4s -cpuprofile=/tmp/interp_cpu.out ./gicg_engine/tests/
//	go tool pprof -top /tmp/interp_cpu.out | head -25
package tests

import (
	"testing"

	"gicg_mono/gicg_engine/factory"
)

func benchmarkGame(b *testing.B) *factory.GameHandle {
	h, err := factory.NewGame(factory.GameConfig{
		DataDir: "../../data",
		Pools:   []string{"native_latest"},
		Players: [2]factory.PConfig{
			{Chars: []factory.CharDef{{Name: "凯亚"}, {Name: "迪卢克"}, {Name: "芭芭拉"}}},
			{Chars: []factory.CharDef{{Name: "砂糖"}, {Name: "菲谢尔"}, {Name: "芭芭拉"}}},
		},
		Seed:      7,
		CardPool:  trainingCardPool(),
		MaxRounds: 10,
	})
	if err != nil {
		b.Fatal(err)
	}
	return h
}

func trainingCardPool() []string {
	return []string{"一掷乾坤", "交给我吧！", "光辉的季节", "兽肉薄荷卷", "冷血之剑", "北地烟熏鸡", "噬星魔鸦", "换班时间", "星天之兆", "最好的伙伴！", "本大爷还没有输！", "派蒙", "流火焦灼", "混元熵增论", "烤蘑菇披萨", "甜甜花酿鸡", "白垩之术", "莲花酥", "蒙德土豆饼", "运筹帷幄", "送你一程", "鸣神大社", "鹤归之时"}
}

// BenchmarkInterpShare — random play loop hitting the two hot queries
// (legal enumeration + step), the same mix MCTS rollouts produce.
func BenchmarkInterpShare(b *testing.B) {
	h := benchmarkGame(b)
	g := h.Game
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		actions := g.GetLegalActions()
		if len(actions) == 0 || g.Winner != -1 {
			b.StopTimer()
			h2 := benchmarkGame(b)
			h = h2
			g = h.Game
			b.StartTimer()
			continue
		}
		g.Step(g.Rng.Intn(len(actions)))
	}
}
