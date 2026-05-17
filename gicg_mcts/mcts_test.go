package mcts

import (
	"sync"
	"testing"
)

// ---- action_id tests --------------------------------------------

func TestActionId_Less_Lexicographic(t *testing.T) {
	a := ActionId{Kind: 0, SubA: 1, SubB: 2}
	b := ActionId{Kind: 0, SubA: 1, SubB: 3}
	if !a.Less(b) {
		t.Errorf("expected %v < %v", a, b)
	}
	if b.Less(a) {
		t.Errorf("expected !(%v < %v)", b, a)
	}
}

func TestActionId_Less_KindDominates(t *testing.T) {
	a := ActionId{Kind: 0, SubA: 999}
	b := ActionId{Kind: 1, SubA: 0}
	if !a.Less(b) {
		t.Errorf("Kind should dominate SubA: %v < %v", a, b)
	}
}

func TestActionId_Equal(t *testing.T) {
	a := ActionId{Kind: 1, SubA: 2, SubB: 3, Payment: [8]int32{1, 0, 0, 0, 0, 0, 0, 2}}
	b := a
	if !a.Equal(b) {
		t.Errorf("equal ActionIds reported unequal")
	}
	b.Payment[7] = 3
	if a.Equal(b) {
		t.Errorf("differing Payment reported equal")
	}
}

// ---- config tests ------------------------------------------------

func TestConfig_LambdaAnneal_Disabled(t *testing.T) {
	cfg := &Config{
		ValueMixLambda:    0.5,
		PriorMixLambda:    0.7,
		LambdaAnnealGames: 0,
	}
	v, p := cfg.EffectiveLambdas()
	if v != 0.5 || p != 0.7 {
		t.Errorf("anneal off: want static (0.5, 0.7), got (%v, %v)", v, p)
	}
}

func TestConfig_LambdaAnneal_Linear(t *testing.T) {
	cfg := &Config{
		LambdaAnnealGames: 100,
		LambdaStart:       0,
		LambdaEnd:         0.8,
		GameIdx:           50, // halfway
	}
	v, _ := cfg.EffectiveLambdas()
	expected := float32(0.4)
	if abs32(v-expected) > 1e-6 {
		t.Errorf("halfway anneal: want %v, got %v", expected, v)
	}
}

func TestConfig_LambdaAnneal_Saturates(t *testing.T) {
	cfg := &Config{
		LambdaAnnealGames: 100,
		LambdaStart:       0,
		LambdaEnd:         0.8,
		GameIdx:           500, // past end
	}
	v, _ := cfg.EffectiveLambdas()
	if v != 0.8 {
		t.Errorf("past-end anneal: want 0.8, got %v", v)
	}
}

// ---- node tests --------------------------------------------------

func TestNode_QP0_Empty(t *testing.T) {
	n := &Node{}
	if n.QP0() != 0 {
		t.Errorf("unvisited QP0 should be 0")
	}
}

func TestNode_QP0_Basic(t *testing.T) {
	n := &Node{}
	n.N.Store(4)
	n.AddW(2.0)
	if got := n.QP0(); abs32(got-0.5) > 1e-4 {
		t.Errorf("QP0 want 0.5, got %v", got)
	}
}

func TestNode_QP0_VirtualLossDilutes(t *testing.T) {
	n := &Node{}
	n.N.Store(2)
	n.AddW(2.0) // Q without VL would be 1.0
	n.NVirtual.Store(2)
	// total = 2 + 2 = 4, Q = 2.0 / 4 = 0.5
	if got := n.QP0(); abs32(got-0.5) > 1e-4 {
		t.Errorf("VL-diluted QP0: want 0.5, got %v", got)
	}
}

func TestNode_AddW_Atomic(t *testing.T) {
	n := &Node{}
	const iters = 1000
	var wg sync.WaitGroup
	for i := 0; i < iters; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			n.AddW(0.1)
			n.N.Add(1)
		}()
	}
	wg.Wait()
	gotN := n.N.Load()
	gotW := n.GetW()
	if gotN != iters {
		t.Errorf("N: want %d, got %d", iters, gotN)
	}
	// 1000 * 0.1 = 100.0, but WScale quantization may introduce small error
	if abs32(gotW-100.0) > 0.01 {
		t.Errorf("W: want 100.0, got %v", gotW)
	}
}

func TestNode_InstallExpansion_Once(t *testing.T) {
	n := &Node{}
	children := []int32{1, 2, 3}
	actions := []ActionId{{Kind: 0}, {Kind: 1}, {Kind: 2}}
	ok := n.InstallExpansion(children, actions, 0.5)
	if !ok {
		t.Fatalf("first install should succeed")
	}
	if !n.Expanded.Load() {
		t.Errorf("Expanded should be true after install")
	}
	if n.NumLegalActions() != 3 {
		t.Errorf("NumLegalActions: want 3, got %d", n.NumLegalActions())
	}
	if n.LeafValueP0() != 0.5 {
		t.Errorf("LeafValueP0: want 0.5, got %v", n.LeafValueP0())
	}

	// Second call should be no-op
	ok2 := n.InstallExpansion([]int32{99}, []ActionId{{Kind: 99}}, 9.9)
	if ok2 {
		t.Errorf("second install should return false")
	}
	if n.NumLegalActions() != 3 {
		t.Errorf("NumLegalActions changed after 2nd install")
	}
}

// ---- pool tests --------------------------------------------------
