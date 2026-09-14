package dmc

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestLogicalIdentityDoesNotMergeSummonTargets(t *testing.T) {
	g := &engine.Game{}
	g.Players[0].Hand = []engine.CardInst{{Ref: 17}}
	a := engine.Action{Kind: engine.ActionCard, HasBuffTarget: true, TargetPlayer: 1, TargetChar: -1, TargetBuff: 3}
	b := a
	b.TargetBuff = 5
	if actionIdentity(g, a) == actionIdentity(g, b) || actionIdentity(g, a) != [5]int{int(engine.ActionCard), 17, 3, 1, -1} {
		t.Fatal("D2 logical action filter would collapse different summon choices")
	}
}

func TestLogicalIdentityDoesNotMergeSupportTargets(t *testing.T) {
	g := &engine.Game{}
	g.Players[0].Hand = []engine.CardInst{{Ref: 17}}
	a := engine.Action{Kind: engine.ActionCard, HasSupportTarget: true, TargetChar: -1}
	b := a
	b.TargetSupport = 3
	if actionIdentity(g, a) == actionIdentity(g, b) || actionIdentity(g, a) != [5]int{int(engine.ActionCard), 17, engine.ObsBuffRows, 0, -1} {
		t.Fatal("D2 logical action filter would collapse support replacement choices")
	}
}
