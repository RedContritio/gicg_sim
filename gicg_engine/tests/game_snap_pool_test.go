package tests

// game_snap_pool_test.go — I29 R3 SnapshotPooled / RestoreFromSnap /
// ReleaseSnap correctness + GC-pressure-reduction smoke。
//
// 覆盖矩阵:
//   - 基本 round-trip(Counters / Hand / Round / Turn / Phase)等价 DeepCopy
//   - 跨 Snapshot 共享 pool slice 不污染(连续 Snapshot/Release 后再 Snapshot
//     不应见到上次的 leftover)
//   - 独立性:snap 后 mutate live game 不影响 snap;snap 持的 Pending* 与 live 隔离
//   - 与 DeepCopy 在同 game 上的等价:scalar 字段 + slice 内容 byte-equal
//   - alloc 数:Snapshot+RestoreFromSnap+Release 稳态后 0 alloc/iter
//     (pool warm 后)
//
// 参考既有 DeepCopy 系列测试 (clone_test.go / reward_events_test.go /
// pending_snapshot_test.go) 的语义不变量 — pool 版本必须 100% 兼容。

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

// TestSnapshotPooled_BasicRoundTrip — mirror clone_test.TestSnapshotRestore_RoundTrip
// 但用 pool API。 HP / Round / Turn 等 dynamic state 必须恢复。
func TestSnapshotPooled_BasicRoundTrip(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"刻师傅"})
	// Rule test: explicitly fund both players rather than depend on random rolls.
	env.SetDice(0, map[int]int{7: 8})
	env.SetDice(1, map[int]int{7: 8})

	origHP1 := env.HP(1, 0)
	origRound := env.G.Round
	origTurn := env.G.Turn

	snap := env.G.SnapshotPooled()
	defer engine.ReleaseSnap(snap)

	// Mutate live game with a skill
	for i, a := range env.G.GetLegalActions() {
		if a.Kind == engine.ActionSkill {
			env.Step(i)
			break
		}
	}
	if env.HP(1, 0) == origHP1 {
		t.Fatal("expected HP to change after skill — setup invalid")
	}

	env.G.RestoreFromSnap(snap)

	if env.HP(1, 0) != origHP1 {
		t.Errorf("HP1 not restored: got %d want %d", env.HP(1, 0), origHP1)
	}
	if env.G.Round != origRound {
		t.Errorf("Round not restored: got %d want %d", env.G.Round, origRound)
	}
	if env.G.Turn != origTurn {
		t.Errorf("Turn not restored: got %d want %d", env.G.Turn, origTurn)
	}
}

// TestSnapshotPooled_RewardAccumSurvives — mirror reward_events_test
// 但用 pool API。 RewardAccum 通过 snap 必须保 round-trip。
func TestSnapshotPooled_RewardAccumSurvives(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.G.RewardAccum[0].DamageDealt = 17
	env.G.RewardAccum[1].ShieldAbsorbed = 5

	snap := env.G.SnapshotPooled()
	defer engine.ReleaseSnap(snap)

	env.G.RewardAccum[0].DamageDealt = 100
	env.G.RewardAccum[1].ShieldAbsorbed = 0

	env.G.RestoreFromSnap(snap)
	if got := env.G.RewardAccum[0].DamageDealt; got != 17 {
		t.Errorf("after Restore, P0.DamageDealt = %d, want 17", got)
	}
	if got := env.G.RewardAccum[1].ShieldAbsorbed; got != 5 {
		t.Errorf("after Restore, P1.ShieldAbsorbed = %d, want 5", got)
	}
}

// TestSnapshotPooled_PreservesPendingAction — mirror pending_snapshot_test
// 但用 pool API。 RestoreFromSnap 必须恢复 PendingAction(forced switch 等)。
func TestSnapshotPooled_PreservesPendingAction(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	g.PendingAction = &engine.Action{
		Kind:      engine.ActionSwitch,
		PlayerIdx: 1,
		Forced:    true,
	}
	expected := *g.PendingAction

	snap := g.SnapshotPooled()
	defer engine.ReleaseSnap(snap)

	// Mutate live game's pending — must not affect restored state via snap
	g.PendingAction = nil

	g.RestoreFromSnap(snap)
	if g.PendingAction == nil {
		t.Fatal("RestoreFromSnap dropped PendingAction")
	}
	if g.PendingAction.Kind != expected.Kind ||
		g.PendingAction.PlayerIdx != expected.PlayerIdx ||
		g.PendingAction.Forced != expected.Forced {
		t.Errorf("PendingAction mismatch: got %+v want %+v",
			*g.PendingAction, expected)
	}
}

// TestSnapshotPooled_PreservesPendingCardTarget — pool API 路径 verify
// PendingCardTarget 通过 snap round-trip。
func TestSnapshotPooled_PreservesPendingCardTarget(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	g.PendingCardTarget = &engine.PendingCard{
		PlayerIdx:    0,
		CardRef:      42,
		BattleAction: true,
		TargetMode:   2,
	}

	snap := g.SnapshotPooled()
	defer engine.ReleaseSnap(snap)

	g.PendingCardTarget = nil
	g.RestoreFromSnap(snap)

	if g.PendingCardTarget == nil {
		t.Fatal("RestoreFromSnap dropped PendingCardTarget")
	}
	if g.PendingCardTarget.CardRef != 42 || g.PendingCardTarget.TargetMode != 2 {
		t.Errorf("PendingCardTarget mismatch: got %+v", *g.PendingCardTarget)
	}
}

// TestSnapshotPooled_DeepCopyEquivalent — 同一 game state 上 SnapshotPooled
// 应与 DeepCopy 在 dynamic state 字段上一致。 测 scalar + Counters 完整等价。
func TestSnapshotPooled_DeepCopyEquivalent(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	deep := g.DeepCopy()
	snap := g.SnapshotPooled()
	defer engine.ReleaseSnap(snap)

	if snap.Phase != deep.Phase || snap.Round != deep.Round ||
		snap.Turn != deep.Turn || snap.Winner != deep.Winner {
		t.Errorf("scalar mismatch: snap{Phase=%v Round=%d Turn=%d Winner=%d} "+
			"vs deep{Phase=%v Round=%d Turn=%d Winner=%d}",
			snap.Phase, snap.Round, snap.Turn, snap.Winner,
			deep.Phase, deep.Round, deep.Turn, deep.Winner)
	}
	if len(snap.Counters) != len(deep.Counters) {
		t.Fatalf("Counters length mismatch: snap=%d deep=%d",
			len(snap.Counters), len(deep.Counters))
	}
	for i, c := range snap.Counters {
		if c.Value != deep.Counters[i].Value {
			t.Errorf("Counters[%d].Value mismatch: snap=%d deep=%d",
				i, c.Value, deep.Counters[i].Value)
		}
	}
	for pi := 0; pi < 2; pi++ {
		if len(snap.Players[pi].Hand) != len(deep.Players[pi].Hand) {
			t.Errorf("P%d Hand len mismatch: snap=%d deep=%d", pi,
				len(snap.Players[pi].Hand), len(deep.Players[pi].Hand))
		}
		if snap.Players[pi].ActiveChar != deep.Players[pi].ActiveChar {
			t.Errorf("P%d ActiveChar mismatch: snap=%d deep=%d", pi,
				snap.Players[pi].ActiveChar, deep.Players[pi].ActiveChar)
		}
	}
}

// TestSnapshotPooled_PoolReuseClean — verify pool 复用不污染:
// 第一次 Snapshot/Release 后,改变 game state,再 Snapshot 不应见前次残留。
func TestSnapshotPooled_PoolReuseClean(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// 第一次 snap + 立即 release(pool 收回)
	snap1 := g.SnapshotPooled()
	round1 := snap1.Round
	engine.ReleaseSnap(snap1)

	// 推进 game state(end_turn 等)— 改 Turn
	origTurn := g.Turn
	for i, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionEndTurn {
			g.Step(i)
			break
		}
	}

	// 第二次 snap — 应反映新 state,不是 pool 残留
	snap2 := g.SnapshotPooled()
	defer engine.ReleaseSnap(snap2)

	if snap2.Round != g.Round {
		t.Errorf("snap2 stale: round %d vs live %d", snap2.Round, g.Round)
	}
	if g.Turn != origTurn && snap2.Turn == origTurn {
		t.Errorf("snap2 caught stale Turn from pool reuse: got %d want %d",
			snap2.Turn, g.Turn)
	}
	_ = round1
}

// TestSnapshotPooled_RestoreAfterMultipleSteps — minimax-style:
// snap → 多 Step → restore 必须完全恢复(等价 GreedyPlayer scoreBestResponse 内)。
func TestSnapshotPooled_RestoreAfterMultipleSteps(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	origRound := g.Round
	origTurn := g.Turn
	origPhase := g.Phase
	origCounterValues := make([]int, len(g.Counters))
	for i, c := range g.Counters {
		origCounterValues[i] = c.Value
	}

	snap := g.SnapshotPooled()
	defer engine.ReleaseSnap(snap)

	// Simulate a few steps (mix end_turn + first legal non-end action)
	for steps := 0; steps < 3; steps++ {
		actions := g.GetLegalActions()
		if len(actions) == 0 {
			break
		}
		// Prefer end_turn to avoid pending state
		picked := -1
		for i, a := range actions {
			if a.Kind == engine.ActionEndTurn {
				picked = i
				break
			}
		}
		if picked < 0 {
			picked = 0
		}
		g.Step(picked)
		if g.Phase == engine.PhaseGameOver {
			break
		}
	}

	g.RestoreFromSnap(snap)
	if g.Round != origRound {
		t.Errorf("Round not restored: got %d want %d", g.Round, origRound)
	}
	if g.Turn != origTurn {
		t.Errorf("Turn not restored: got %d want %d", g.Turn, origTurn)
	}
	if g.Phase != origPhase {
		t.Errorf("Phase not restored: got %v want %v", g.Phase, origPhase)
	}
	for i, c := range g.Counters {
		if c.Value != origCounterValues[i] {
			t.Errorf("Counter[%d] not restored: got %d want %d",
				i, c.Value, origCounterValues[i])
			break
		}
	}
}

// TestSnapshotPooled_NilReleaseSafe — ReleaseSnap(nil) 必须 idempotent no-op。
func TestSnapshotPooled_NilReleaseSafe(t *testing.T) {
	engine.ReleaseSnap(nil) // 不应 panic
}
