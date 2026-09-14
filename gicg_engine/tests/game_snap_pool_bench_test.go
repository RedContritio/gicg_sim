package tests

// Snapshot allocation and restore benchmarks. Correctness tests live in game_snap_pool_test.go.

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

// BenchmarkSnapshotPooled_Restore — 测 SnapshotPooled+RestoreFromSnap+Release
// 稳态 alloc/op。 pool warm 后预期 0-2 allocs/op(只 RecentDamageEvents
// fresh alloc 路径,空 ring 时 0 alloc)。 对比 BenchmarkGame_DeepCopy_Restore
// (16 alloc/32KB) 看 GC pressure reduction。
func BenchmarkSnapshotPooled_Restore(b *testing.B) {
	t := &testing.T{}
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	if t.Failed() {
		b.Fatal("setup failed")
	}
	g := env.G

	// Warm the pool to amortize first-Snapshot slice alloc
	for i := 0; i < 4; i++ {
		s := g.SnapshotPooled()
		engine.ReleaseSnap(s)
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		snap := g.SnapshotPooled()
		g.RestoreFromSnap(snap)
		engine.ReleaseSnap(snap)
	}
}

// BenchmarkSnapshotPooled_Only — 单 SnapshotPooled+Release(无 Restore)
// alloc 测。 对比 BenchmarkGame_DeepCopy_Only (14 alloc/26KB)。
func BenchmarkSnapshotPooled_Only(b *testing.B) {
	t := &testing.T{}
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	if t.Failed() {
		b.Fatal("setup failed")
	}
	g := env.G

	for i := 0; i < 4; i++ {
		s := g.SnapshotPooled()
		engine.ReleaseSnap(s)
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		snap := g.SnapshotPooled()
		engine.ReleaseSnap(snap)
	}
}

// BenchmarkGame_Step_NoOp_Pooled — 对比 BenchmarkGame_Step_NoOp
// (821 alloc/114KB)的 pooled 版本。 Step 内部 alloc 不受 pool 影响,
// 但 snap/restore 路径的 16 allocs/32KB 应消除 → 期望 ~805 alloc/82KB。
func BenchmarkGame_Step_NoOp_Pooled(b *testing.B) {
	t := &testing.T{}
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	if t.Failed() {
		b.Fatal("setup failed")
	}
	g := env.G

	endTurnIdx := -1
	for i, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionEndTurn {
			endTurnIdx = i
			break
		}
	}
	if endTurnIdx < 0 {
		b.Skip("no end_turn action at game start")
	}

	for i := 0; i < 4; i++ {
		s := g.SnapshotPooled()
		engine.ReleaseSnap(s)
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		snap := g.SnapshotPooled()
		g.Step(endTurnIdx)
		g.RestoreFromSnap(snap)
		engine.ReleaseSnap(snap)
	}
}
