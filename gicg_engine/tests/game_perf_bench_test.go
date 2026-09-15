// game_perf_bench_test.go — micro-benchmarks for Game.DeepCopy / Step / RestoreFrom hot path。
//
// I29 P2 acceptance FAIL: Mac N=4 Go subprocess 9.76 fps/actor vs Python mp 51.03 (5x slower)。
// 重要 audit finding (2026-05-25):Go 和 Python *共用* `game.DeepCopy` (Python cgo also calls
// h.Game.DeepCopy()),所以 5x gap 不来自 DeepCopy 实现差。 本 bench 给 Go 端 DeepCopy/Step
// 的 baseline alloc+wall 数据,供后续 cross-check Python mp ctypes path 的 same ops。
//
// 跑法:
//
//	go test -bench=BenchmarkGame -benchmem -benchtime=5s ./gicg_engine/tests/
package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// BenchmarkGame_DeepCopy_Restore — 测 DeepCopy + RestoreFrom cycle wall + alloc。
// 与 GreedyPlayer minimax 内 hot path 等价:每 candidate snap → step → restore。
func BenchmarkGame_DeepCopy_Restore(b *testing.B) {
	t := &testing.T{}
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	if t.Failed() {
		b.Fatal("setup failed")
	}
	g := env.G

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		snap := g.DeepCopy()
		g.RestoreFrom(snap)
	}
}

// BenchmarkGame_DeepCopy_Only — 单 DeepCopy alloc cost (无 restore)。
// 反映 sync.Pool 优化前的 alloc 频率上限。
func BenchmarkGame_DeepCopy_Only(b *testing.B) {
	t := &testing.T{}
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	if t.Failed() {
		b.Fatal("setup failed")
	}
	g := env.G

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_ = g.DeepCopy()
	}
}

// BenchmarkGame_Step_NoOp — 测 game.Step 单次 wall (用 end_turn action — 最 minimal step)。
// 反映 minimax recursion 内 step 单次开销 (cgo path 同等)。
func BenchmarkGame_Step_NoOp(b *testing.B) {
	t := &testing.T{}
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	if t.Failed() {
		b.Fatal("setup failed")
	}
	g := env.G

	// Find end_turn action index — 最简 step (no side effect)
	endTurnIdx := -1
	for i, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionEndTurn {
			endTurnIdx = i
			break
		}
	}
	if endTurnIdx < 0 {
		b.Skip("no end_turn action at game start (phase != PhaseAction)")
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		// Snap → step → restore (与 minimax recursion 等价 sequence)
		snap := g.DeepCopy()
		g.Step(endTurnIdx)
		g.RestoreFrom(snap)
	}
}
