package mcts

import (
	"fmt"
	"sync/atomic"
)

// Pool is a fixed-capacity node allocator for one MCTS search. Nodes
// are indexed by int32 pool-index (see node.Node.children []int32),
// avoiding per-node heap allocation and cache-unfriendly pointer
// chasing. Reset() reclaims all nodes between searches.
//
// Concurrency:
//   - Alloc() is atomic and safe from any goroutine during a search.
//   - Get(idx) is safe concurrently with Alloc() only if idx was
//     returned by a prior Alloc() that happens-before the Get.
//   - Reset() must not race with Alloc/Get — caller's responsibility,
//     enforced by calling Reset only between searches.
type Pool struct {
	nodes []Node
	next  atomic.Int32
}

// NewPool creates a pool with fixed capacity. Typical sizing:
// n_rollouts + 2·max_legal_actions (one per new leaf + root children).
// For 200 rollouts × 40 avg legal: 200 + 80 ≈ 300 nodes enough; we
// over-provision to 1024 for slack.
func NewPool(capacity int) *Pool {
	return &Pool{nodes: make([]Node, capacity)}
}

// Alloc reserves one node and returns (index, *Node). The node's
// atomics are zeroed (Reset()) so it's ready to use. Panics if the
// pool is exhausted — indicates sizing bug.
func (p *Pool) Alloc() (int32, *Node) {
	idx := p.next.Add(1) - 1
	if int(idx) >= len(p.nodes) {
		panic(fmt.Sprintf("mcts: pool exhausted at %d (cap %d)", idx, len(p.nodes)))
	}
	n := &p.nodes[idx]
	n.Reset()
	return idx, n
}

// Get returns the node at the given pool index. The returned pointer
// is valid until Reset() is called.
func (p *Pool) Get(idx int32) *Node {
	return &p.nodes[idx]
}

// Reset marks all nodes as reclaimable. Must not race with any
// Alloc or Get. Typically called at the start of each search.
func (p *Pool) Reset() {
	p.next.Store(0)
}

// Size returns the number of nodes currently allocated.
func (p *Pool) Size() int32 {
	return p.next.Load()
}

// Capacity returns the maximum number of nodes this pool can hold.
func (p *Pool) Capacity() int {
	return len(p.nodes)
}
