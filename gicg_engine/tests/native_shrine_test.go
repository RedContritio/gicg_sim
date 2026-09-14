package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
)

func TestNativeShrineCopiesRecheckParityAndKeepSeparateLimits(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprintf("P%d", p), func(t *testing.T) {
			e := nativeTalentGame(t, "凯亚")
			auditPlay(t, e, p, "鸣神大社")
			auditPlay(t, e, p, "鸣神大社")
			if e.DiceTotal(p) != 10 {
				t.Fatal("two shrines must cost six dice")
			}
			ids := [2]uint64{e.G.Players[p].Supports[0].BuffID, e.G.Players[p].Supports[1].BuffID}
			for n := 1; n <= 5; n++ {
				e.SetDice(p, map[int]int{engine.DiceColorOmni: 16})
				e.G.WriteCounter(e.RT.Chars.BySlot[1-p][0].HPCounterID, engine.OpSet, 10)
				auditSkill(t, e, p, "仪典剑术")
				wantDice := 14
				if n == 5 {
					wantDice = 13
				}
				if e.DiceTotal(p) != wantDice {
					t.Fatalf("skill %d dice=%d want=%d", n, e.DiceTotal(p), wantDice)
				}
				for i, id := range ids {
					progress, err := e.G.BuffProgress(id)
					want := min(2, max(0, n-i*2))
					if err != nil || progress != want {
						t.Fatalf("skill %d shrine %d progress=%d want=%d err=%v", n, i, progress, want, err)
					}
				}
			}
			// Exhausted support remains in play; only its per-round budget resets.
			for round := 0; round < 4; round++ {
				nativeNextRound(t, e)
				if len(e.G.Players[p].Supports) != 2 {
					t.Fatal("shrine incorrectly has a round lifetime")
				}
				for _, id := range ids {
					if used, err := e.G.BuffProgress(id); err != nil || used != 0 {
						t.Fatal("per-round budget did not reset")
					}
				}
			}
		})
	}
}

func TestNativeShrineEvenDiceEnemyAndCloneObservation(t *testing.T) {
	cfg := factory.GameConfig{DataDir: dataDir, Pools: []string{"native_latest"}, Seed: 42}
	for p := range cfg.Players {
		cfg.Players[p] = factory.PConfig{Chars: []factory.CharDef{{Name: "凯亚"}, {Name: "砂糖"}, {Name: "芭芭拉"}},
			Deck: []string{"甜甜花酿鸡"}}
	}
	h, err := factory.NewGame(cfg)
	if err != nil {
		t.Fatal(err)
	}
	h.Game.Step(0)
	h.Game.Step(0)
	h.Game.GetLegalActions()
	e := &GameEnv{G: h.Game, RT: h.RT, T: t}
	for p := 0; p < 2; p++ {
		e.G.Players[p].Hand = nil
		e.SetDice(p, map[int]int{engine.DiceColorOmni: 16})
	}
	auditPlay(t, e, 0, "鸣神大社")
	id := e.G.Players[0].Supports[0].BuffID
	e.SetDice(0, map[int]int{engine.DiceColorOmni: 15})
	auditSkill(t, e, 0, "仪典剑术")
	if e.DiceTotal(0) != 12 {
		t.Fatal("even dice triggered shrine")
	}
	auditSkill(t, e, 1, "仪典剑术")
	if used, _ := e.G.BuffProgress(id); used != 0 {
		t.Fatal("enemy skill consumed own shrine")
	}
	e.SetDice(0, map[int]int{engine.DiceColorOmni: 16})
	auditSkill(t, e, 0, "仪典剑术")
	clone := e.RT.Clone()
	branch := &GameEnv{G: clone.Game, RT: clone, T: t}
	branch.SetDice(0, map[int]int{engine.DiceColorOmni: 16})
	auditSkill(t, branch, 0, "仪典剑术")
	if used, _ := e.G.BuffProgress(id); used != 1 {
		t.Fatal("clone changed source progress")
	}
	if used, _ := branch.G.BuffProgress(id); used != 2 {
		t.Fatal("clone did not retain independent progress")
	}
	for _, subject := range []*GameEnv{e, branch} {
		want, _ := subject.G.BuffProgress(id)
		obs := subject.G.BuildDynamicObs(0)
		rows := obs[len(obs)-engine.ObsBuffSlots:]
		seen, supportSeen := false, false
		for offset := 0; offset < len(rows); offset += engine.ObsBuffFields {
			row := rows[offset : offset+engine.ObsBuffFields]
			if row[0] == 1 && row[12] == engine.EntitySupport && row[1] == 0 {
				if row[3] != 1 || row[5] != int32(want) {
					t.Fatal("support row lost its associated effect state")
				}
				supportSeen = true
			}
			if row[0] == 1 && row[12] == engine.EntityBuff && row[8] == int32(engine.HookSkillUse) {
				if row[5] != int32(want) {
					t.Fatal("NN observation lost per-instance progress")
				}
				seen = true
			}
		}
		if !seen || !supportSeen {
			t.Fatal("shrine effect absent from NN observation")
		}
	}
}
