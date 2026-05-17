package enginev2

import "testing"

// A12 perf microbench: Game.Step + Clone wall (1k iter)
func TestA12PerfMicrobench(t *testing.T) {
	g := NewGame()
	for i := 0; i < 20; i++ {
		s := g.DeclareScalar("s"+intToStr(i), 5, 0, 10, Owner{Player: i % 2})
		s.Tag = TagHP
	}
	for i := 0; i < 5; i++ {
		c := g.DeclareCollection("c"+intToStr(i), 10, Owner{Player: i % 2}, "instance")
		for j := 0; j < 5; j++ {
			c.Append(&CardRef{Ref: j, CostTotal: j})
		}
	}

	for i := 0; i < 1000; i++ {
		_ = g.Clone()
	}

	e := NewEngine(g)
	hpRef := g.Scalars["s0"]
	hpRef.Tag = TagHP
	for i := 0; i < 1000; i++ {
		ctx := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
			Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
		ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hpRef, Delta: -1})
		e.FireSubAction(ctx)
		hpRef.Value = 5
	}
}

// A11 Game.Clone 深拷贝 bit-exact
func TestGameCloneBitExact(t *testing.T) {
	g := NewGame()
	g.DeclareScalar("a", 5, 0, 10, Owner{Player: 0})
	c := g.DeclareCollection("h", 5, Owner{Player: 0}, "instance")
	c.Append(&CardRef{Ref: 1})
	c.Append(&CardRef{Ref: 2})

	g2 := g.Clone()
	if g2.Scalars["a"].Value != 5 || g2.Collections["h"].Len() != 2 {
		t.Fatalf("clone state 不一致")
	}
	g2.Scalars["a"].Value = 99
	if g.Scalars["a"].Value != 5 {
		t.Fatalf("clone 共享指针 — 不是真深拷")
	}

	// LastTransitions 也应深拷
	g.AppendTransition(TransitionEntry{SubAction: SubActionDealDamage, Value: 7})
	g3 := g.Clone()
	if len(g3.LastTransitions) != 1 || g3.LastTransitions[0].Value != 7 {
		t.Fatalf("LastTransitions 没深拷")
	}
	g3.LastTransitions[0].Value = 99
	if g.LastTransitions[0].Value != 7 {
		t.Fatalf("LastTransitions 共享底层 array")
	}
}
