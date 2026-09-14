package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestCurrentRules_FoodOnlySkillDamage(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "佛跳墙")
			auditPlay(t, e, p, "测试卡_碎片")
			if e.HP(1-p, 0) != 14 || e.counterByChar("佛跳墙_buff", p, 0) != 1 {
				t.Fatal("card damage consumed skill-only food")
			}
			hp := e.RT.Chars.BySlot[1-p][0].HPCounterID
			for _, source := range []engine.Source{engine.SrcStatus, engine.SrcSummon, engine.SrcReaction, engine.SrcSupport} {
				before := e.HP(1-p, 0)
				e.G.ExecuteEffect(engine.EventFrame{Player: p, Char: 0, Source: source}, func(g *engine.Game) {
					g.DealDamage(hp, engine.ElemPhysical, 1, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
				})
				if e.HP(1-p, 0) != before-1 || e.counterByChar("佛跳墙_buff", p, 0) != 1 {
					t.Fatalf("source %v consumed food", source)
				}
			}
			before := e.HP(1-p, 0)
			auditSkill(t, e, p, "枪")
			if e.HP(1-p, 0) != before-4 || e.counterByChar("佛跳墙_buff", p, 0) != 0 {
				t.Fatal("skill must consume +2 once")
			}
			auditSkill(t, e, p, "枪")
			if e.HP(1-p, 0) != before-6 {
				t.Fatal("second skill gained food bonus")
			}
		})
	}
}

func TestCurrentRules_UnusedFoodExpiresOnBench(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "佛跳墙")
			auditSwitch(t, e, p, 1)
			e.playToRoundEnd(t)
			if e.counterByChar("佛跳墙_buff", p, 0) != 0 {
				t.Fatal("unused food on bench survived round end")
			}
			e.SetDice(p, map[int]int{engine.DiceColorOmni: 8})
			auditSwitch(t, e, p, 0)
			before := e.HP(1-p, 0)
			auditSkill(t, e, p, "枪")
			if e.HP(1-p, 0) != before-2 {
				t.Fatal("expired food boosted next-round skill")
			}
		})
	}
}

func TestCurrentRules_BenchMarkHitsOnlyMarkedCharacter(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			e.SetDice(1-p, map[int]int{engine.DiceColorOmni: 8})
			auditPlay(t, e, p, "蝶鳞")
			auditSkill(t, e, p, "枪")
			auditSwitch(t, e, 1-p, 1)
			before := [2]int{e.HP(1-p, 0), e.HP(1-p, 1)}
			e.playToRoundEnd(t)
			if e.HP(1-p, 0) != before[0]-1 || e.HP(1-p, 1) != before[1] {
				t.Fatal("bench mark missed victim or hit unmarked active")
			}
			if e.counterByChar("蝶印", 1-p, 0) != 0 || e.counterByChar("火元素附着", 1-p, 1) != 0 {
				t.Fatal("mark not cleared or unmarked target received elemental event")
			}
			e.playToRoundEnd(t)
			if e.HP(1-p, 0) != before[0]-1 {
				t.Fatal("mark triggered again next round")
			}
		})
	}
}

func TestCurrentRules_MultipleMarksResumeAfterDeath(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			e.SetDice(1-p, map[int]int{engine.DiceColorOmni: 8})
			auditPlay(t, e, p, "蝶鳞")
			auditSkill(t, e, p, "枪")
			auditSwitch(t, e, 1-p, 1)
			auditSkill(t, e, p, "枪")
			auditSwitch(t, e, 1-p, 0)
			e.G.Counters[e.RT.Chars.BySlot[1-p][0].HPCounterID].Value = 1
			before := e.HP(1-p, 1)
			e.G.Turn = p
			e.G.Step(e.FindAction(engine.ActionEndTurn, ""))
			if e.G.Step(e.FindAction(engine.ActionEndTurn, "")) != engine.StepNeedTarget {
				t.Fatal("mark death did not pause")
			}
			if e.HP(1-p, 1) != before {
				t.Fatal("second mark ran ahead of replacement input")
			}
			for i := 0; i < 2; i++ {
				rt := e.RT.Clone()
				branch := &GameEnv{G: rt.Game, RT: rt, T: t}
				branch.G.Step(0)
				if branch.G.PendingAction != nil || branch.G.Phase != engine.PhaseRoundStart || branch.HP(1-p, 1) != before-1 {
					t.Fatal("remaining mark did not resume exactly once")
				}
				for c := 0; c < 2; c++ {
					if branch.counterByChar("蝶印", 1-p, c) != 0 {
						t.Fatal("mark not cleared")
					}
				}
			}
			if e.G.PendingAction == nil || e.HP(1-p, 1) != before {
				t.Fatal("clone changed source")
			}
		})
	}
}

func TestCurrentRules_DamageSelectorRejectsNonCounter(t *testing.T) {
	e := currentCardGame(t, 0)
	_, err := execDSL(e, `deal_damage(Target.EnemyAll, Element.Fire, 1, {target_counter=1})`)
	if err == nil {
		t.Fatal("invalid selector must not silently hit every character")
	}
}
