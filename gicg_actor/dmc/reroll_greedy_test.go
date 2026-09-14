package dmc

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestRerollIdentityAndBaseline(t *testing.T) {
	g := &engine.Game{PendingDice: &engine.DiceSelection{Player: 0, Remaining: 2}}
	g.Players[0].Chars = []engine.CharInfo{{Alive: true, Element: engine.ElemIce}}
	g.PendingDice.Pool = [engine.DiceColorCount]int{2, 2, 0, 0, 0, 0, 0, 2}
	for color, want := range map[int]int{engine.DiceColorFire: 2, engine.DiceColorIce: 0, engine.DiceColorOmni: 0, engine.DiceColorCount: 0} {
		g.PendingDice.Color = color
		if got := greedyRerollChoice(g); got != want {
			t.Fatalf("color %d choice=%d want %d", color, got, want)
		}
	}
	a := engine.Action{Kind: engine.ActionReroll, Index: 2, RerollColor: 0}
	b := a
	b.Index = 1
	c := a
	c.RerollColor = 1
	if actionIdentity(g, a) == actionIdentity(g, b) || actionIdentity(g, a) == actionIdentity(g, c) ||
		actionIdentity(g, a) != [5]int{int(engine.ActionReroll), 2, 0, -1, -1} {
		t.Fatal("reroll count/color collapsed in logical action identity")
	}
}
