package engine

// game_snap.go — sync.Pool-backed lightweight snapshot for hot-path
// speculative rollout (GreedyPlayer minimax + MCTS rollout + capi
// GameSnapshot/Restore).
//
// I29 R3 (2026-05-25):pure-Go Mac M4 bench 显示 `g.DeepCopy()` 单次 14
// allocs / 26 KB(slice 重 alloc 主因:Counters / Hand / Deck /
// Discard / Supports × 2 players + RecentDamageEvents)。 多 actor
// 并发下(Go subprocess N=4 共享 single heap),DeepCopy 累计 GC
// pressure 是 Mac N=4 production fps 落后 Python mp(每子进程独立
// heap)的主因之一。
//
// 设计:
//   - GameSnap 是独立 struct,只持游戏 dynamic state(immutable
//     Hooks / Perms / Names / Obs / Extra 不入 snap)。
//   - sync.Pool 重用 GameSnap struct + 内嵌 slice backing array;
//     Snapshot() 从 pool 取 → in-place copy(slice 容量足时 0 alloc)。
//   - Hot-path caller:`snap := g.SnapshotPooled(); defer engine.ReleaseSnap(snap)
//     ... g.RestoreFromSnap(snap)`。
//   - 命名:Snapshot() 已被 round.go 用于 *StateSnapshot(EventLog 状态),
//     故新 API 用 SnapshotPooled 避免冲突。
//   - 保留旧 DeepCopy()/RestoreFrom(*Game) — 测试 / interp.Runtime.Clone
//     等非 hot-path 路径还需 full *Game 语义(SetPlayerHand 等 mutator
//     仅 *Game 提供)。
//
// 注意:GameSnap 跨 goroutine 复用 必须 经 Release。 caller 不持引用
// 后再 Release 是 use-after-free,行为未定义。

import (
	"math/rand"
	"sync"
)

// GameSnap captures all dynamic state needed to restore a Game to a
// quiescent point (between Step calls; event stack drained).
// Layout mirrors the fields written by DeepCopy() but excludes
// pointers to immutable / shared metadata (Hooks, Obs, name maps,
// CounterPerm/HookPerm, Extra) — those are held by the live *Game
// and don't need snapshotting.
type GameSnap struct {
	// --- Dynamic scalars ---
	Phase    Phase
	Round    int
	Turn     int
	FirstEnd int
	Winner   int
	BaseSeed int64
	depth    int

	DicePaid     [2][DiceColorCount]int
	DiceTunedOut [2][DiceColorCount]int
	DiceTunedIn  [2][DiceColorCount]int
	RewardAccum  [2]RewardEvents
	Preparing    [2]int

	// --- Variable-length slices (pool-reused backing arrays) ---
	Counters           []Counter
	RecentDamageEvents []RecentDamageEvent

	// Per-player snapshot (Hand/Deck/Discard/Supports use pool-reused
	// backing arrays; Chars only carries .Alive flag since CharInfo's
	// other fields are immutable post-bind).
	Players [2]playerSnap

	// --- Pending state (cleared if nil on snapshot, value-copied if set) ---
	PendingAction        *Action
	HasPendingAction     bool
	PendingCardTarget    PendingCard
	HasPendingCardTarget bool

	// --- RNG seeds (captured via Int63 fork, restored by re-seeding) ---
	RngSeed     int64
	HasRng      bool
	DeckSeeds   [2]int64
	DeckRngSeed [2]int64
	HasDeckRng  [2]bool

	// reactionKind: PendingReactionKind value (transient, usually 0 at
	// quiescent points; included for completeness).
	PendingReactionKind int
}

// playerSnap captures dynamic PlayerState fields. CharInfo is reduced
// to per-char Alive flag (Skills / Element / PlayerIdx / CharIdx are
// static identity, restored by reference to the live Game's Chars).
type playerSnap struct {
	ActiveChar  int
	DeclaredEnd bool
	AliveFlags  []bool // len == len(g.Players[pi].Chars)
	Hand        []CardInst
	Deck        []CardInst
	Discard     []CardInst
	Supports    []SupportInst
}

// snapPool reuses *GameSnap allocations. Slices inside the snap are
// reused across cycles when capacities are sufficient (caller-side
// `append(s[:0], src...)` pattern in Snapshot).
var snapPool = sync.Pool{
	New: func() any {
		return &GameSnap{}
	},
}

// SnapshotPooled captures the receiver's dynamic state into a pool-backed
// GameSnap. Caller must release via ReleaseSnap when done (typically
// `defer engine.ReleaseSnap(snap)` after take, before RestoreFromSnap).
//
// Quiescent contract: caller must only invoke at Step boundaries
// (eventStack drained, damageLogStack empty). Same contract as
// existing DeepCopy. See docs/az/decisions.md D2.
//
// 命名:Snapshot() 已被 round.go 占用(返 *StateSnapshot 给 EventLog),
// 故 pool-backed 新 API 取名 SnapshotPooled。
func (g *Game) SnapshotPooled() *GameSnap {
	snap := snapPool.Get().(*GameSnap)

	// Scalars (value copy)
	snap.Phase = g.Phase
	snap.Round = g.Round
	snap.Turn = g.Turn
	snap.FirstEnd = g.FirstEnd
	snap.Winner = g.Winner
	snap.BaseSeed = g.BaseSeed
	snap.depth = 0 // never carry recursion depth
	snap.DicePaid = g.DicePaid
	snap.DiceTunedOut = g.DiceTunedOut
	snap.DiceTunedIn = g.DiceTunedIn
	snap.RewardAccum = g.RewardAccum
	snap.Preparing = g.Preparing
	snap.PendingReactionKind = g.PendingReactionKind

	// Counters: reuse backing array
	snap.Counters = append(snap.Counters[:0], g.Counters...)

	// RecentDamageEvents: ring buffer with embedded Modifiers slice.
	// Truncate to zero first to drop stale Modifier sub-slices' alias,
	// then re-append. Each event's Modifiers slice is reused if cap
	// suffices.
	if cap(snap.RecentDamageEvents) < len(g.RecentDamageEvents) {
		snap.RecentDamageEvents = make([]RecentDamageEvent, len(g.RecentDamageEvents))
	} else {
		snap.RecentDamageEvents = snap.RecentDamageEvents[:len(g.RecentDamageEvents)]
	}
	for i, e := range g.RecentDamageEvents {
		// Copy scalars
		dst := &snap.RecentDamageEvents[i]
		mods := dst.Modifiers
		*dst = e
		// Re-attach pooled Modifiers backing array
		if len(e.Modifiers) > 0 {
			dst.Modifiers = append(mods[:0], e.Modifiers...)
		} else {
			dst.Modifiers = mods[:0]
		}
	}

	// Per-player snapshots
	for pi := 0; pi < 2; pi++ {
		src := &g.Players[pi]
		dst := &snap.Players[pi]
		dst.ActiveChar = src.ActiveChar
		dst.DeclaredEnd = src.DeclaredEnd

		// AliveFlags — derived from CharInfo.Alive
		if cap(dst.AliveFlags) < len(src.Chars) {
			dst.AliveFlags = make([]bool, len(src.Chars))
		} else {
			dst.AliveFlags = dst.AliveFlags[:len(src.Chars)]
		}
		for ci, ch := range src.Chars {
			dst.AliveFlags[ci] = ch.Alive
		}

		dst.Hand = append(dst.Hand[:0], src.Hand...)
		dst.Deck = append(dst.Deck[:0], src.Deck...)
		dst.Discard = append(dst.Discard[:0], src.Discard...)
		dst.Supports = append(dst.Supports[:0], src.Supports...)
	}

	// Pending state — value copy via has-flag pattern (avoid *Action /
	// *PendingCard alloc for the common nil case).
	if g.PendingAction != nil {
		snap.PendingAction = g.PendingAction
		snap.HasPendingAction = true
	} else {
		snap.PendingAction = nil
		snap.HasPendingAction = false
	}
	if g.PendingCardTarget != nil {
		snap.PendingCardTarget = *g.PendingCardTarget
		snap.HasPendingCardTarget = true
	} else {
		snap.HasPendingCardTarget = false
	}

	// RNG fork via Int63 — preserves DeepCopy semantics (re-seeded
	// restore yields the same downstream sequence).
	if g.Rng != nil {
		snap.RngSeed = g.Rng.Int63()
		snap.HasRng = true
	} else {
		snap.HasRng = false
	}
	snap.DeckSeeds = g.DeckSeeds
	for pi := 0; pi < 2; pi++ {
		if g.DeckRngs[pi] != nil {
			snap.DeckRngSeed[pi] = g.DeckRngs[pi].Int63()
			snap.HasDeckRng[pi] = true
		} else {
			snap.HasDeckRng[pi] = false
		}
	}

	return snap
}

// RestoreFromSnap copies dynamic state from snap into the receiver.
// Mirror of RestoreFrom(*Game) but uses pool-backed GameSnap.
//
// Quiescent contract: same as Snapshot — caller must only invoke at
// Step boundaries. Counter slices must have matching lengths (snap
// from a different ruleset is unsupported; mismatch → silent return,
// matching legacy RestoreFrom behavior).
func (g *Game) RestoreFromSnap(snap *GameSnap) {
	if len(g.Counters) != len(snap.Counters) {
		return
	}
	copy(g.Counters, snap.Counters)

	for pi := 0; pi < 2; pi++ {
		src := &snap.Players[pi]
		dst := &g.Players[pi]
		for ci := range dst.Chars {
			if ci < len(src.AliveFlags) {
				dst.Chars[ci].Alive = src.AliveFlags[ci]
			}
		}
		dst.ActiveChar = src.ActiveChar
		dst.DeclaredEnd = src.DeclaredEnd
		dst.Hand = append(dst.Hand[:0], src.Hand...)
		dst.Deck = append(dst.Deck[:0], src.Deck...)
		dst.Discard = append(dst.Discard[:0], src.Discard...)
		dst.Supports = append(dst.Supports[:0], src.Supports...)
	}

	g.Phase = snap.Phase
	g.Round = snap.Round
	g.Turn = snap.Turn
	g.FirstEnd = snap.FirstEnd
	g.Winner = snap.Winner
	g.BaseSeed = snap.BaseSeed
	g.DicePaid = snap.DicePaid
	g.DiceTunedOut = snap.DiceTunedOut
	g.DiceTunedIn = snap.DiceTunedIn
	g.RewardAccum = snap.RewardAccum
	g.Preparing = snap.Preparing
	g.PendingReactionKind = snap.PendingReactionKind

	if snap.HasPendingAction {
		g.PendingAction = snap.PendingAction
	} else {
		g.PendingAction = nil
	}
	if snap.HasPendingCardTarget {
		target := snap.PendingCardTarget // value copy out of snap
		g.PendingCardTarget = &target
	} else {
		g.PendingCardTarget = nil
	}

	g.eventStack = nil
	g.depth = 0

	// RecentDamageEvents — restore ring. Existing g.RecentDamageEvents
	// can't be safely reused (caller may hold references via obs encode
	// path that's still alive); allocate fresh per restore (matches
	// existing RestoreFrom behavior).
	if len(snap.RecentDamageEvents) > 0 {
		g.RecentDamageEvents = make([]RecentDamageEvent, len(snap.RecentDamageEvents))
		for i, e := range snap.RecentDamageEvents {
			g.RecentDamageEvents[i] = e
			if len(e.Modifiers) > 0 {
				g.RecentDamageEvents[i].Modifiers = append([]Modifier(nil), e.Modifiers...)
			}
		}
	} else {
		g.RecentDamageEvents = nil
	}
	g.damageLogStack = nil

	if snap.HasRng {
		if g.Rng != nil {
			// Reuse existing *Rand by re-seeding — avoids the
			// rand.New + NewSource alloc pair per Restore (5+ ns
			// saved + 2 fewer allocs/op on hot path).
			g.Rng.Seed(snap.RngSeed)
		} else {
			g.Rng = rand.New(rand.NewSource(snap.RngSeed))
		}
	}
	g.DeckSeeds = snap.DeckSeeds
	for pi := 0; pi < 2; pi++ {
		if snap.HasDeckRng[pi] {
			if g.DeckRngs[pi] != nil {
				g.DeckRngs[pi].Seed(snap.DeckRngSeed[pi])
			} else {
				g.DeckRngs[pi] = rand.New(rand.NewSource(snap.DeckRngSeed[pi]))
			}
		}
	}
}

// ReleaseSnap returns snap to the pool for reuse. Caller must not
// access snap after release. Idempotent: nil snap is a no-op.
//
// Slice fields are NOT zeroed — their backing arrays are reused on
// next Snapshot via `append(s[:0], src...)`. CardInst / SupportInst
// are POD (no pointer fields) so leftover entries can't pin GC-tracked
// memory.
func ReleaseSnap(snap *GameSnap) {
	if snap == nil {
		return
	}
	// Clear pointer fields to avoid pinning unrelated *Action objects
	// in the pool's idle state.
	snap.PendingAction = nil
	snap.HasPendingAction = false
	snap.HasPendingCardTarget = false
	snapPool.Put(snap)
}
