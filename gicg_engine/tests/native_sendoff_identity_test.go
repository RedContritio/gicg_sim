package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestNativeSendOffKeepsIdentityAcrossPaymentPreparation(t *testing.T) {
	for _, replaceTarget := range []bool{false, true} {
		e := nativeTalentGame(t, "菲谢尔")
		auditPlay(t, e, 0, "派蒙") // earlier live effect whose removal shifts target position
		auditSkill(t, e, 1, "夜巡影翼")
		e.G.Turn = 0
		e.giveCard(t, 0, "送你一程")
		uses := findCounterIDPerPlayer(e, "奥兹", 1)
		ref := e.cardRef("送你一程")
		e.G.Hooks.Register(engine.Hook{Type: engine.HookActionPrepare,
			Fn: func(g *engine.Game, ctx *engine.EventContext) {
				if ctx.ActionCtx != engine.ActPlayCard || ctx.CardRef != ref {
					return
				}
				g.RemoveSupportAt(0, 0)
				if replaceTarget {
					g.WriteCounter(uses, engine.OpSet, 0)
					g.WriteCounter(uses, engine.OpSet, 2) // new instance, same definition
				}
			}})
		found := false
		for index, action := range e.G.GetLegalActions() {
			if !action.HasBuffTarget {
				continue
			}
			found = true
			e.G.Step(index)
			break
		}
		want := 0
		if replaceTarget {
			want = 2 // removed original is a null target, not the new Oz
		}
		if !found || e.G.Counters[uses].Value != want || len(e.G.Players[0].Supports) != 0 {
			t.Fatal("send off followed shifted position or replaced definition rather than original identity")
		}
	}
}
