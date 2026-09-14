package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestCurrentCards_SelectedTargetSurvivesDeferredCloneRestore(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			// Supplement the real food with a deferred effect using the same selection.
			_, err := execDSL(e, `local card = get_card("美味烧鸡")
on_card_play(function(ctx)
 if ctx.card_ref ~= card then return end
 defer_fn(function() heal(Target.CardTarget, 1) end)
end)`)
			if err != nil {
				t.Fatal(err)
			}
			for side := 0; side < 2; side++ {
				for c := 0; c < 2; c++ {
					e.G.Counters[e.RT.Chars.BySlot[side][c].HPCounterID].Value = 8
				}
			}
			e.giveCard(t, p, "美味烧鸡")
			snapshot := e.G.SnapshotPooled()
			defer engine.ReleaseSnap(snapshot)
			for attempt := 0; attempt < 3; attempt++ {
				branch := e.RT.Clone()
				branch.Game.RestoreFromSnap(snapshot)
				selected := -1
				for i, a := range branch.Game.GetLegalActions() {
					if a.Kind == engine.ActionCard && a.HasTarget && a.TargetPlayer == p && a.TargetChar == 1 {
						selected = i
						break
					}
				}
				if selected < 0 {
					t.Fatal("backline target unavailable")
				}
				branch.Game.Step(selected)
				for side := 0; side < 2; side++ {
					for c := 0; c < 2; c++ {
						id := branch.Chars.BySlot[side][c].HPCounterID
						want := 8
						if side == p && c == 1 {
							want = 10
						}
						if got := branch.Game.ReadCounter(id); got != want {
							t.Fatalf("P%d C%d hp=%d want %d", side, c, got, want)
						}
						if e.G.ReadCounter(id) != 8 {
							t.Fatal("clone changed source")
						}
					}
				}
			}
		})
	}
}

func TestCurrentCards_EnergyAtCapDoesNotTriggerTransfer(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "西风长枪")
			e.G.Counters[e.RT.Chars.BySlot[p][0].EnergyCounterID].Value = 3
			auditPlay(t, e, p, "占星")
			if e.Energy(p, 1) != 0 {
				t.Fatal("zero actual energy gain triggered transfer")
			}
		})
	}
}

func TestCurrentCards_XuanBingReplacesOneReaction(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "玄冰")
			e.setBuffToOne(t, "冰元素附着", 1-p, 0)
			hp := e.RT.Chars.BySlot[1-p][0].HPCounterID
			e.G.ExecuteEffect(engine.EventFrame{Player: p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
				g.DealDamage(hp, engine.ElemElectro, 1, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
			})
			if e.HP(1-p, 0) != 13 || e.HP(1-p, 1) != 14 {
				t.Fatalf("wrong AoE damage: %d/%d", e.HP(1-p, 0), e.HP(1-p, 1))
			}
			if e.counterByChar("冰元素附着", 1-p, 1) != 1 {
				t.Fatal("replacement should be ice, not piercing")
			}
			if e.G.Counters[findCounterIDPerPlayer(e, "玄冰_active", p)].Value != 0 {
				t.Fatal("replacement not consumed")
			}
			if e.HP(p, 0) != 15 || e.HP(p, 1) != 15 {
				t.Fatal("reaction hit owner")
			}
		})
	}
}

func TestCurrentCards_MysteryWaterAfterSkillAndReset(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditSkill(t, e, p, "枪")
			e.setBuffToOne(t, "火元素附着", 1-p, 0)
			before := e.HP(1-p, 0)
			auditPlay(t, e, p, "测试卡_神秘水流")
			if before-e.HP(1-p, 0) != 4 {
				t.Fatal("after a skill, 2 water + 2 vaporize expected")
			}
			e.playToRoundEnd(t)
			e.G.GetLegalActions()
			if e.G.ReadCounter(findCounterIDPerPlayer(e, "神秘水流_used_skill", p)) != 0 {
				t.Fatal("skill flag did not reset next round")
			}
		})
	}
}
