package mcts

import (
	"sync"
	"testing"
)

func TestPool_Alloc_Sequential(t *testing.T) {
	p := NewPool(16)
	if p.Size() != 0 {
		t.Errorf("new pool size: want 0, got %d", p.Size())
	}
	for i := int32(0); i < 10; i++ {
		idx, n := p.Alloc()
		if idx != i {
			t.Errorf("Alloc #%d: want idx %d, got %d", i, i, idx)
		}
		if n == nil {
			t.Errorf("Alloc returned nil node")
		}
	}
	if p.Size() != 10 {
		t.Errorf("size after 10 Alloc: want 10, got %d", p.Size())
	}
}

func TestPool_Alloc_Concurrent(t *testing.T) {
	p := NewPool(1000)
	const n = 500
	var wg sync.WaitGroup
	seen := make([]bool, n)
	var mu sync.Mutex
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			idx, _ := p.Alloc()
			mu.Lock()
			if int(idx) < n {
				if seen[idx] {
					t.Errorf("duplicate Alloc index %d", idx)
				}
				seen[idx] = true
			}
			mu.Unlock()
		}()
	}
	wg.Wait()
	if p.Size() != n {
		t.Errorf("concurrent Alloc size: want %d, got %d", n, p.Size())
	}
}

func TestPool_Reset_Reclaims(t *testing.T) {
	p := NewPool(16)
	for i := 0; i < 10; i++ {
		p.Alloc()
	}
	p.Reset()
	if p.Size() != 0 {
		t.Errorf("after Reset: want size 0, got %d", p.Size())
	}
	// Next Alloc should reuse slot 0
	idx, _ := p.Alloc()
	if idx != 0 {
		t.Errorf("post-Reset Alloc: want idx 0, got %d", idx)
	}
}

func TestPool_Exhaust_Panics(t *testing.T) {
	p := NewPool(2)
	p.Alloc()
	p.Alloc()
	defer func() {
		if r := recover(); r == nil {
			t.Errorf("3rd Alloc should panic")
		}
	}()
	p.Alloc() // should panic
}

// ---- puct tests --------------------------------------------------

func TestPUCTScore_Basic(t *testing.T) {
	// c_puct = 1.4, P = 0.5, N_avail = 4, N = 0, NV = 0
	// Q = 0 (no visits yet), U = 1.4 * 0.5 * sqrt(4) / (1 + 0) = 1.4
	child := &Node{Prior: 0.5}
	child.NAvail.Store(4)
	got := PUCTScore(child, 0, 1.4)
	want := float32(1.4)
	if abs32(got-want) > 1e-5 {
		t.Errorf("PUCT basic: want %v, got %v", want, got)
	}
}

func TestPUCTScore_VirtualLossReducesScore(t *testing.T) {
	child := &Node{Prior: 0.5}
	child.NAvail.Store(4)
	// Without VL: score = 0 + 1.4 * 0.5 * 2 / (1 + 0) = 1.4
	// With VL=1:   score = 0 + 1.4 * 0.5 * 2 / (1 + 1) = 0.7
	child.NVirtual.Store(1)
	got := PUCTScore(child, 0, 1.4)
	want := float32(0.7)
	if abs32(got-want) > 1e-5 {
		t.Errorf("PUCT with VL: want %v, got %v", want, got)
	}
}

func TestPUCTScore_PerspectiveFlip(t *testing.T) {
	// Q = +0.8 for P0. From parent.turn=1, should flip to -0.8.
	child := &Node{Prior: 0}
	child.N.Store(1)
	child.AddW(0.8)
	// Prior=0 so U=0, score = q only
	if got := PUCTScore(child, 0, 1.0); abs32(got-0.8) > 1e-4 {
		t.Errorf("parent.turn=0: want +0.8, got %v", got)
	}
	if got := PUCTScore(child, 1, 1.0); abs32(got-(-0.8)) > 1e-4 {
		t.Errorf("parent.turn=1: want -0.8, got %v", got)
	}
}

// ---- backup tests ------------------------------------------------

func TestBackup_IncrementsPath(t *testing.T) {
	p := NewPool(4)
	_, root := p.Alloc()
	_, mid := p.Alloc()
	_, leaf := p.Alloc()
	// Apply VL (simulating earlier descent)
	path := []int32{0, 1, 2}
	AddVirtualLoss(p, path)
	if root.NVirtual.Load() != 1 || mid.NVirtual.Load() != 1 || leaf.NVirtual.Load() != 1 {
		t.Errorf("AddVirtualLoss: VL not incremented on all path nodes")
	}
	// Backup with value 0.5
	Backup(p, path, 0.5)
	for i, idx := range path {
		n := p.Get(idx)
		if n.N.Load() != 1 {
			t.Errorf("path[%d] N: want 1, got %d", i, n.N.Load())
		}
		if abs32(n.GetW()-0.5) > 1e-4 {
			t.Errorf("path[%d] W: want 0.5, got %v", i, n.GetW())
		}
		if n.NVirtual.Load() != 0 {
			t.Errorf("path[%d] VL: want 0 (reverted), got %d", i, n.NVirtual.Load())
		}
	}
}

func TestRevertVirtualLoss_NoVisit(t *testing.T) {
	p := NewPool(3)
	p.Alloc()
	p.Alloc()
	path := []int32{0, 1}
	AddVirtualLoss(p, path)
	RevertVirtualLoss(p, path)
	for _, idx := range path {
		n := p.Get(idx)
		if n.NVirtual.Load() != 0 {
			t.Errorf("VL should be back to 0, got %d", n.NVirtual.Load())
		}
		if n.N.Load() != 0 {
			t.Errorf("N should not be touched by revert, got %d", n.N.Load())
		}
	}
}

// ---- helpers -----------------------------------------------------

func abs32(x float32) float32 {
	if x < 0 {
		return -x
	}
	return x
}
