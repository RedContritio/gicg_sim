package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestNativeRerollPaidOnceAndResumesCardHooks(t *testing.T) {
	for _, p := range []int{0, 1} {
		e := nativeTalentGame(t, "凯亚")
		e.SetDice(p, map[int]int{engine.DiceColorFire: 2, engine.DiceColorOmni: 1})
		e.G.Turn = p
		e.giveCard(t, p, "一掷乾坤")
		ref := e.cardRef("一掷乾坤")
		marker := e.G.CreateCounter(0, 0, 10)
		e.G.Hooks.Register(engine.Hook{Type: engine.HookCardPlay, Priority: -1000,
			Fn: func(g *engine.Game, ctx *engine.EventContext) {
				if ctx.CardRef == ref {
					g.WriteCounter(marker, engine.OpAdd, 1)
				}
			}})
		hand, discard := len(e.G.Players[p].Hand), len(e.G.Players[p].Discard)
		found := false
		for index, a := range e.G.GetLegalActions() {
			if a.Kind == engine.ActionCard && e.G.Players[p].Hand[a.Index].Ref == ref {
				found = e.G.Step(index) == engine.StepNeedTarget
				break
			}
		}
		if !found || e.G.PendingDice == nil || e.G.Counters[marker].Value != 0 {
			t.Fatal("DSL card did not suspend before remaining hooks")
		}
		confirmations := 0
		for e.G.PendingDice != nil {
			f := e.G.PendingDice
			n := 0
			if f.Color == engine.DiceColorCount {
				confirmations++
			} else {
				n = f.Pool[f.Color] // every color, including omni, may be selected
			}
			e.G.Step(n)
		}
		if confirmations != 2 || e.G.Turn != p || e.DiceTotal(p) != 3 || e.G.Counters[marker].Value != 1 ||
			len(e.G.Players[p].Hand) != hand-1 || len(e.G.Players[p].Discard) != discard+1 {
			t.Fatal("reroll changed action ownership, paid twice or resumed incorrectly")
		}
	}
}
