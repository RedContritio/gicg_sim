package tests

import (
	"bytes"
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/record"
)

func TestNativeSendOffChoosesOneEnemySummon(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprintf("P%d", p), func(t *testing.T) {
			e := nativeTalentGame(t, "菲谢尔")
			e.G.Turn = p
			e.giveCard(t, p, "送你一程")
			if e.FindAction(engine.ActionCard, "送你一程") >= 0 {
				t.Fatal("send off playable with no enemy summon")
			}
			auditSkill(t, e, p, "夜巡影翼")
			e.G.Turn = p
			if e.FindAction(engine.ActionCard, "送你一程") >= 0 {
				t.Fatal("send off can target own summon")
			}
			auditSkill(t, e, 1-p, "夜巡影翼")
			auditSwitch(t, e, 1-p, 2)
			e.G.WriteCounter(e.RT.Chars.BySlot[1-p][2].EnergyCounterID, engine.OpSet, 2)
			auditSkill(t, e, 1-p, "禁·风灵作成·柒伍同构贰型")
			e.G.Turn = p
			count := 0
			for i, action := range e.G.GetLegalActions() {
				if action.Kind != engine.ActionCard || !action.HasBuffTarget {
					continue
				}
				count++
				if action.HasTarget || action.TargetPlayer != 1-p || action.TargetChar != -1 ||
					engine.ActionCharRef(action) != -2-action.TargetBuff {
					t.Fatal("buff selection was confused with a character target")
				}
				buff := e.G.Buffs[action.TargetBuff]
				counter := e.G.BuffDefinitions[buff.Definition].CounterID
				name := e.G.CounterNames[counter]
				clone := e.RT.Clone()
				replay := e.RT.Clone()
				input := engine.InputForAction(action)
				r := record.Replayer{Runtime: replay, Rec: &record.Record{Rounds: []record.Round{{Number: 1,
					Actions: []record.Action{{Kind: record.ActCard, Player: p, Name: "送你一程", Input: &input, TargetPlayer: -1}},
				}}}}
				if err := r.Step(1, 0); err != nil {
					t.Fatal(err)
				}
				branch := &GameEnv{G: clone.Game, RT: clone, T: t}
				before := branch.DiceTotal(p)
				if branch.G.Step(i) != engine.StepContinue || branch.DiceTotal(p) != before-2 || branch.G.Turn != p {
					t.Fatal("send off payment, continuation, or fast-action turn incorrect")
				}
				if !bytes.Equal(checkpointBytes(t, branch.G), checkpointBytes(t, replay.Game)) {
					t.Fatal("send off replay changed selected summon or payment")
				}
				wantOz, wantWind := 2, 3
				if name == "奥兹" {
					wantOz = 0
				} else if name == "大型风灵" {
					wantWind = 1
				} else {
					t.Fatal("unexpected summon target")
				}
				if branch.G.Counters[findCounterIDPerPlayer(branch, "奥兹", 1-p)].Value != wantOz ||
					branch.G.Counters[findCounterIDPerPlayer(branch, "大型风灵", 1-p)].Value != wantWind ||
					branch.G.Counters[findCounterIDPerPlayer(branch, "奥兹", p)].Value != 2 {
					t.Fatal("send off changed the wrong summon or wrong number of uses")
				}
				if e.countHandCard(p, "送你一程") != 1 || branch.countHandCard(p, "送你一程") != 0 {
					t.Fatal("clone or hand consumption incorrect")
				}
				if err := branch.G.RestoreCheckpoint(checkpointBytes(t, branch.G)); err != nil {
					t.Fatal(err)
				}
			}
			if count != 2 {
				t.Fatalf("got %d choices, want two distinct enemy summons", count)
			}
		})
	}
}
