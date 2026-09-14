package mcts

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestSummonTargetsRemainDistinctSearchActions(t *testing.T) {
	g := &engine.Game{}
	g.Players[0].Hand = []engine.CardInst{{Ref: 17}, {Ref: 17}}
	a := engine.Action{Kind: engine.ActionCard, PlayerIdx: 0, Index: 0,
		HasBuffTarget: true, TargetPlayer: 1, TargetChar: -1, TargetBuff: 3}
	a.DicePayment[7] = 2
	b := a
	b.TargetBuff = 5
	first, second := actionToId(g, a), actionToId(g, b)
	if first.Equal(second) || first.SubB != 3 || second.SubB != 5 || first.SubC != 1 || first.SubD != -1 {
		t.Fatal("different summon choices merged in search identity")
	}
	b = a
	b.Index = 1
	if !first.Equal(actionToId(g, b)) {
		t.Fatal("same card in another hand slot changed logical action identity")
	}
}

func TestSupportTargetsRemainDistinctSearchActions(t *testing.T) {
	g := &engine.Game{}
	g.Players[0].Hand = []engine.CardInst{{Ref: 17}, {Ref: 17}}
	a := engine.Action{Kind: engine.ActionCard, HasSupportTarget: true, TargetChar: -1}
	a.DicePayment[7] = 3
	b := a
	b.TargetSupport = 3
	first, second := actionToId(g, a), actionToId(g, b)
	if first.Equal(second) || first.SubB != engine.ObsBuffRows || second.SubB != engine.ObsBuffRows+3 || first.SubC != 0 || first.SubD != -1 {
		t.Fatal("different support replacement choices merged in search identity")
	}
	b = a
	b.Index = 1
	if !first.Equal(actionToId(g, b)) {
		t.Fatal("duplicate hand copy changed logical replacement identity")
	}
}

func TestRerollChoicesRemainDistinctSearchActions(t *testing.T) {
	g := &engine.Game{}
	a := engine.Action{Kind: engine.ActionReroll, Index: 2, RerollColor: 0}
	b, c := a, a
	b.Index, c.RerollColor = 1, 1
	id := actionToId(g, a)
	if id.Equal(actionToId(g, b)) || id.Equal(actionToId(g, c)) || id.SubA != 2 || id.SubB != 0 {
		t.Fatal("reroll count/color collapsed in search identity")
	}
}
