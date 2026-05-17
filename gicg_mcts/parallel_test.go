package mcts

import (
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
)

func TestRunRollouts_AllRolloutsExecute(t *testing.T) {
	const n = 200
	var count atomic.Int32
	errs := RunRollouts(n, 4, func(rolloutIdx int) error {
		count.Add(1)
		return nil
	})
	if len(errs) != 0 {
		t.Errorf("unexpected errors: %v", errs)
	}
	if count.Load() != n {
		t.Errorf("expected %d rollouts, got %d", n, count.Load())
	}
}

func TestRunRollouts_UniqueIndices(t *testing.T) {
	const n = 500
	var mu sync.Mutex
	seen := make(map[int]int)
	errs := RunRollouts(n, 8, func(rolloutIdx int) error {
		mu.Lock()
		seen[rolloutIdx]++
		mu.Unlock()
		return nil
	})
	if len(errs) != 0 {
		t.Errorf("unexpected errors: %v", errs)
	}
	if len(seen) != n {
		t.Errorf("unique indices: want %d, got %d", n, len(seen))
	}
	for i := 0; i < n; i++ {
		if seen[i] != 1 {
			t.Errorf("rollout %d seen %d times (want 1)", i, seen[i])
		}
	}
}

func TestRunRollouts_PanicRecovered(t *testing.T) {
	const n = 20
	var reached atomic.Int32
	errs := RunRollouts(n, 4, func(rolloutIdx int) error {
		if rolloutIdx == 5 || rolloutIdx == 12 {
			panic(fmt.Sprintf("test panic %d", rolloutIdx))
		}
		reached.Add(1)
		return nil
	})
	if len(errs) != 2 {
		t.Errorf("expected 2 panic errors, got %d: %v", len(errs), errs)
	}
	// Other rollouts should have completed
	if reached.Load() != n-2 {
		t.Errorf("non-panicking rollouts: want %d, got %d", n-2, reached.Load())
	}
}

func TestRunRollouts_ErrorCollected(t *testing.T) {
	const n = 10
	errs := RunRollouts(n, 3, func(rolloutIdx int) error {
		if rolloutIdx%3 == 0 {
			return errors.New("intentional")
		}
		return nil
	})
	expected := (n + 2) / 3 // 0, 3, 6, 9 → 4
	if len(errs) != expected {
		t.Errorf("expected %d errors, got %d", expected, len(errs))
	}
}

func TestRunRollouts_SingleGoroutine(t *testing.T) {
	// parallel=1 should still work
	const n = 10
	var count atomic.Int32
	RunRollouts(n, 1, func(rolloutIdx int) error {
		count.Add(1)
		return nil
	})
	if count.Load() != n {
		t.Errorf("parallel=1: want %d, got %d", n, count.Load())
	}
}

func TestRunRollouts_ZeroRollouts(t *testing.T) {
	errs := RunRollouts(0, 4, func(rolloutIdx int) error {
		t.Errorf("rolloutFunc should not be called")
		return nil
	})
	if len(errs) != 0 {
		t.Errorf("no rollouts → no errors, got %v", errs)
	}
}

func TestRunRollouts_ParallelExceedsN(t *testing.T) {
	// parallel > n should work (extra goroutines idle)
	const n = 3
	var count atomic.Int32
	errs := RunRollouts(n, 10, func(rolloutIdx int) error {
		count.Add(1)
		return nil
	})
	if len(errs) != 0 {
		t.Errorf("unexpected errors: %v", errs)
	}
	if count.Load() != n {
		t.Errorf("want %d, got %d", n, count.Load())
	}
}

func TestRunRollouts_TreeCoordination(t *testing.T) {
	// Simulate real MCTS: shared tree, goroutines do VL + backup.
	// Check final state: N == n_rollouts, no leaked VL.
	pool := NewPool(100)
	_, root := pool.Alloc()
	// Pretend root is expanded
	root.numLegal = 1
	root.children = []int32{1}
	root.actions = []ActionId{{Kind: 0}}
	root.Expanded.Store(true)
	_, _ = pool.Alloc() // child at idx 1

	const n = 100
	errs := RunRollouts(n, 4, func(rolloutIdx int) error {
		path := []int32{0, 1}
		AddVirtualLoss(pool, path)
		// ... simulate eval/rollout (trivial)
		// Success path: Backup
		Backup(pool, path, 0.1)
		return nil
	})
	if len(errs) != 0 {
		t.Errorf("unexpected errors: %v", errs)
	}

	// Verify tree statistics
	r := pool.Get(0)
	c := pool.Get(1)
	if r.N.Load() != n {
		t.Errorf("root.N: want %d, got %d", n, r.N.Load())
	}
	if c.N.Load() != n {
		t.Errorf("child.N: want %d, got %d", n, c.N.Load())
	}
	if r.NVirtual.Load() != 0 {
		t.Errorf("root VL leaked: %d", r.NVirtual.Load())
	}
	if c.NVirtual.Load() != 0 {
		t.Errorf("child VL leaked: %d", c.NVirtual.Load())
	}
}

func TestDeriveRolloutSeed_Deterministic(t *testing.T) {
	s1 := DeriveRolloutSeed(12345, 7)
	s2 := DeriveRolloutSeed(12345, 7)
	if s1 != s2 {
		t.Errorf("same inputs → same seed: %d vs %d", s1, s2)
	}
}

func TestDeriveRolloutSeed_DifferentIdx(t *testing.T) {
	seen := make(map[uint64]bool)
	for i := 0; i < 100; i++ {
		s := DeriveRolloutSeed(42, i)
		if seen[s] {
			t.Errorf("collision at idx %d: seed %d", i, s)
		}
		seen[s] = true
	}
}

func TestDeriveRolloutSeed_DifferentMaster(t *testing.T) {
	s1 := DeriveRolloutSeed(1, 5)
	s2 := DeriveRolloutSeed(2, 5)
	if s1 == s2 {
		t.Errorf("different masters should give different seeds")
	}
}
