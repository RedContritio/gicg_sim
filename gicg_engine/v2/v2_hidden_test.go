package enginev2

import "testing"

// A19 server-side SelectMax (沙中遗事)
func TestA19SelectMaxPlainKeyFn(t *testing.T) {
	g := NewGame()
	enemyHand := g.DeclareCollection("hand_p1", 5, Owner{Player: 1, Char: -1}, "instance")
	enemyHand.HiddenFrom = HiddenFrom{0}
	enemyHand.Items = []Item{
		&CardRef{Ref: 10, CostTotal: 1},
		&CardRef{Ref: 20, CostTotal: 3},
		&CardRef{Ref: 30, CostTotal: 2},
	}

	maxIdx := enemyHand.SelectMax(KeyCostTotal)
	if maxIdx != 1 {
		t.Errorf("expected idx=1 (cost 3), got %d", maxIdx)
	}
	if enemyHand.IsVisibleTo(0) {
		t.Errorf("expected hand hidden from p0")
	}
	if !enemyHand.IsVisibleTo(1) {
		t.Errorf("expected hand visible to p1 (owner)")
	}
}

// A14 ownership-bound mask: swap 后 mask 仍正确。
func TestA14OwnershipBoundSwapMask(t *testing.T) {
	g := NewGame()
	handP0 := g.DeclareCollection("hand_p0", 5, Owner{Player: 0, Char: -1}, "instance")
	handP0.HiddenFrom = HiddenFrom{1}
	handP0.Items = []Item{&CardRef{Ref: 1}, &CardRef{Ref: 2}}

	handP1 := g.DeclareCollection("hand_p1", 5, Owner{Player: 1, Char: -1}, "instance")
	handP1.HiddenFrom = HiddenFrom{0}
	handP1.Items = []Item{&CardRef{Ref: 11}, &CardRef{Ref: 12}, &CardRef{Ref: 13}}

	SwapCollections(handP0, handP1)

	if handP0.Owner.Player != 0 {
		t.Errorf("hand_p0 owner 应不变 = 0, got %d", handP0.Owner.Player)
	}
	if !handP0.IsVisibleTo(0) {
		t.Errorf("hand_p0 应对 p0 可见 (owner 不变)")
	}
	if handP0.IsVisibleTo(1) {
		t.Errorf("hand_p0 仍 hidden from p1")
	}
	if handP0.Len() != 3 {
		t.Errorf("hand_p0 swap 后应 = 3 cards, got %d", handP0.Len())
	}
	if c, ok := handP0.At(0).(*CardRef); !ok || c.Ref != 11 {
		t.Errorf("hand_p0[0] swap 后应 = CardRef(Ref=11), got %v", handP0.At(0))
	}
}

// A19 plain_key_fn enum 限制 + typed Item dispatch
func TestA19PlainKeyFnEnumClosure(t *testing.T) {
	g := NewGame()
	c := g.DeclareCollection("targets", 5, SystemOwner(), "shared")
	c.Items = []Item{
		&SummonRef{Ref: 1, Hp: 5},
		&SummonRef{Ref: 2, Hp: 2},
		&SummonRef{Ref: 3, Hp: 8},
	}
	if c.SelectMin(KeyHpAsc) != 1 {
		t.Errorf("KeyHpAsc 选最低 hp 应 idx=1")
	}
	if c.SelectMax(KeyHpAsc) != 2 {
		t.Errorf("KeyHpAsc max 应 idx=2 (hp=8)")
	}
}
