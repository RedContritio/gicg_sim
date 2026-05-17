package mcts

import (
	"sync"
	"sync/atomic"
)

// WScale lets us store W (float32) as int64 for atomic add. Chosen
// 2^20 ≈ 1e6 → 6 decimal digits precision, more than enough for MCTS
// (visit-count-weighted averages).
const WScale = 1 << 20

// Node is one state in the IS-UCT tree. Statistics are P0-perspective
// throughout (PUCT flips sign based on parent.turn at query time).
//
// Concurrency model (A5 decision):
//   - Hot fields (N, WScaled, NVirtual, NAvail) use sync/atomic — no
//     lock on the rollout hot path.
//   - Children/priors are written exactly once (at expand) and read
//     many times (every descent); guarded by expandMu as RWMutex.
//   - Expanded is atomic.Bool; CAS ensures only one goroutine
//     initializes children for a given node.
type Node struct {
	// --- Immutable after construction ---------------------------------
	Turn      int8    // who acts at this node (0/1), -1 for untouched
	Terminal  bool    // engine terminal at construction?
	TerminalZ float32 // if Terminal, cached _terminal_z(winner), P0 perspective
	Prior     float32 // inherited from parent's eval; 0 for root (root prior is on children)

	// --- Hot-path atomics ---------------------------------------------
	N        atomic.Int64 // visit count
	WScaled  atomic.Int64 // W × WScale, atomic-safe accumulator
	NVirtual atomic.Int32 // in-flight rollouts through this edge
	NAvail   atomic.Int32 // # determinizations where this child was legal
	Expanded atomic.Bool  // set once, guards children/priors initialization

	// --- Expand-once, read-many -------------------------------------
	expandMu sync.RWMutex
	// Children are pool indices into the owning Search's Pool. Using
	// int32 indices instead of *Node avoids cache-unfriendly pointer
	// chasing and makes the pool packable.
	children []int32    // len == NumLegal after expand; -1 until a child's Node allocated
	actions  []ActionId // children[i] corresponds to action actions[i]
	numLegal int32      // len of actions

	// --- Leaf value (set at expansion, read during backup) ------------
	// P0 perspective. For non-terminal leaves, = λ·V_net + (1-λ)·z_rollout.
	// For terminal nodes, = TerminalZ.
	leafValueP0 float32
}

// AddW atomically adds a float32 value to W.
func (n *Node) AddW(v float32) {
	n.WScaled.Add(int64(v * WScale))
}

// GetW returns the current W as float32.
func (n *Node) GetW() float32 {
	return float32(n.WScaled.Load()) / WScale
}

// QP0 returns the P0-perspective mean value. Includes in-flight
// (virtual) visits in the denominator so Q dilutes toward 0 under VL.
// Matches Python MCTSNode.q_p0.
func (n *Node) QP0() float32 {
	n_val := n.N.Load()
	vl := int64(n.NVirtual.Load())
	total := n_val + vl
	if total == 0 {
		return 0
	}
	return n.GetW() / float32(total)
}

// LeafValueP0 returns the leaf value set at expansion. Safe to call
// after Expanded.Load() == true (happens-before guaranteed via atomic
// store at end of expansion).
func (n *Node) LeafValueP0() float32 {
	return n.leafValueP0
}

// SetLeafValueP0 is called exactly once during expansion, before
// Expanded is marked true.
func (n *Node) SetLeafValueP0(v float32) {
	n.leafValueP0 = v
}

// NumLegalActions returns the number of children (== number of legal
// actions at this node's state). Valid only after Expanded == true.
func (n *Node) NumLegalActions() int32 {
	return n.numLegal
}

// Children returns the child pool-index slice. Caller must hold an
// RLock via BeginRead / EndRead. Do NOT mutate the returned slice.
func (n *Node) Children() []int32 {
	return n.children
}

// Actions returns the ActionId slice aligned with Children.
func (n *Node) Actions() []ActionId {
	return n.actions
}

// BeginRead acquires a read lock on the children/actions slices. Must
// be paired with EndRead. Use during descent (PUCT selection reads
// children) — multiple readers OK, blocks while a writer (expand) is
// in progress.
func (n *Node) BeginRead() {
	n.expandMu.RLock()
}

// EndRead releases the read lock.
func (n *Node) EndRead() {
	n.expandMu.RUnlock()
}

// InstallExpansion writes children + actions + leafValueP0 under the
// write lock and sets Expanded atomically. Idempotent: if Expanded
// is already true, returns false and does nothing (caller should
// treat this as "someone else beat me to it").
//
// Invariant: only one goroutine wins the CAS on Expanded; losers
// read the already-written data via BeginRead.
func (n *Node) InstallExpansion(children []int32, actions []ActionId, leafValueP0 float32) bool {
	n.expandMu.Lock()
	defer n.expandMu.Unlock()
	if n.Expanded.Load() {
		return false
	}
	n.children = children
	n.actions = actions
	n.numLegal = int32(len(children))
	n.leafValueP0 = leafValueP0
	n.Expanded.Store(true)
	return true
}

// AppendChildren adds new (child, action) entries to an already-
// expanded node. Used by IS-MCTS when a determinization reveals a
// legal action that wasn't present in any earlier rollout's legal
// set — the new action gets a child with its own prior and the
// parent's numLegal grows. Caller must hold no other lock on the
// node (AppendChildren takes the write lock internally).
//
// Precondition: len(newChildren) == len(newActions) and node is
// already Expanded. No dedup — caller filters to truly-new actions
// after acquiring the lock (via a check-under-lock idiom) to avoid
// double-insertion races.
func (n *Node) AppendChildren(newChildren []int32, newActions []ActionId) {
	n.expandMu.Lock()
	defer n.expandMu.Unlock()
	n.children = append(n.children, newChildren...)
	n.actions = append(n.actions, newActions...)
	n.numLegal = int32(len(n.children))
}

// LockForAppend takes the write lock for the check-then-append
// pattern. Returned slices are a snapshot of the current state
// (callers compare against this to decide what to append). Must be
// paired with UnlockAfterAppend.
func (n *Node) LockForAppend() ([]int32, []ActionId) {
	n.expandMu.Lock()
	return n.children, n.actions
}

// AppendUnlocked appends while holding the write lock from a prior
// LockForAppend. Does NOT release the lock.
func (n *Node) AppendUnlocked(newChildren []int32, newActions []ActionId) {
	n.children = append(n.children, newChildren...)
	n.actions = append(n.actions, newActions...)
	n.numLegal = int32(len(n.children))
}

// UnlockAfterAppend releases the write lock from LockForAppend.
func (n *Node) UnlockAfterAppend() {
	n.expandMu.Unlock()
}

// Reset zeros all atomics + clears Expanded. Called by the pool when
// a node slot is reclaimed between searches.
func (n *Node) Reset() {
	n.N.Store(0)
	n.WScaled.Store(0)
	n.NVirtual.Store(0)
	n.NAvail.Store(0)
	n.Expanded.Store(false)
	// Non-atomic fields are overwritten on next use; no need to clear.
}
