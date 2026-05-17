package mcts

import (
	"hash/maphash"
	"sync"
	"unsafe"
)

// evalKeyHasher is shared across a single Search. The seed is
// captured once per process (maphash.MakeSeed) so two runs in the
// same process share keys — which is what we want when evaluating
// whether a cross-search cache would hit. Different processes use
// different seeds, which doesn't matter for within-run statistics.
var evalHashSeed = maphash.MakeSeed()

// evalUniqueTracker counts unique eval requests (keyed by
// hash(dyn_obs || refs || pay)) observed during one Search. Used as
// a preflight measurement for whether a state-level eval cache
// would be worthwhile: unique/total is the hit-rate upper bound
// achievable by a perfect cache of unlimited capacity.
//
// Overhead: ~2us maphash + ~300ns sync.Map LoadOrStore per eval
// request, vs ~5ms eval round-trip — well below measurement noise.
type evalUniqueTracker struct {
	keys sync.Map // uint64 → struct{}
	n    atomicInt64Ref
}

// atomicInt64Ref avoids importing sync/atomic just for one counter.
// Using sync.Map.LoadOrStore's second return (loaded) is enough to
// detect uniqueness, but we also want the cumulative insert count —
// so we count explicitly.
type atomicInt64Ref struct{ v int64 }

// Observe hashes one eval request's flat buffers and records the
// key. Returns true if this key was new (i.e., a cache miss would
// have occurred).
func (t *evalUniqueTracker) Observe(dyn, refs, pay []int32) bool {
	var h maphash.Hash
	h.SetSeed(evalHashSeed)
	writeInt32SliceBytes(&h, dyn)
	writeInt32SliceBytes(&h, refs)
	writeInt32SliceBytes(&h, pay)
	key := h.Sum64()
	_, loaded := t.keys.LoadOrStore(key, struct{}{})
	return !loaded
}

// UniqueCount returns the number of distinct eval keys observed.
// Called once at Search exit — no concurrent Observe by that point.
func (t *evalUniqueTracker) UniqueCount() int64 {
	var n int64
	t.keys.Range(func(_, _ any) bool {
		n++
		return true
	})
	return n
}

// writeInt32SliceBytes feeds the underlying bytes of a []int32 to
// the hasher without a copy. Safe because maphash reads its input
// synchronously; the slice is live for the duration of the call.
func writeInt32SliceBytes(h *maphash.Hash, s []int32) {
	if len(s) == 0 {
		return
	}
	b := unsafe.Slice((*byte)(unsafe.Pointer(&s[0])), len(s)*4)
	h.Write(b)
}
