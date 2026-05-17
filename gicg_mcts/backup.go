package mcts

// Backup walks the path from leaf back to root, incrementing N,
// accumulating W, and reverting the virtual-loss addition that was
// applied during descent. valueP0 is the leaf's value from P0
// perspective — same sign convention as stored W throughout the tree
// (PUCT applies the parent.turn flip at query time).
//
// path[0] == root, path[len-1] == leaf (both inclusive).
//
// Mirrors training/mcts.py::_commit_parallel_rollout: backs up the
// leaf value along the path and decrements each node's N_virtual.
func Backup(pool *Pool, path []int32, valueP0 float32) {
	for _, idx := range path {
		n := pool.Get(idx)
		n.N.Add(1)
		n.AddW(valueP0)
		n.NVirtual.Add(-1)
	}
}

// RevertVirtualLoss undoes virtual_loss additions on a path without
// recording a real visit. Called when a rollout is abandoned (panic,
// eval error) so the tree statistics don't carry phantom VL.
func RevertVirtualLoss(pool *Pool, path []int32) {
	for _, idx := range path {
		pool.Get(idx).NVirtual.Add(-1)
	}
}

// AddVirtualLoss increments virtual-loss counters along a path. Used
// during descent, before eval/rollout, to discourage concurrent
// goroutines from following the same path. Matched 1-for-1 with a
// later Backup (success) or RevertVirtualLoss (failure).
func AddVirtualLoss(pool *Pool, path []int32) {
	for _, idx := range path {
		pool.Get(idx).NVirtual.Add(1)
	}
}
