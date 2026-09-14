package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"reflect"
	"testing"
)

func TestBuffInstances_FIFOAndLifecycle(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, first := range []string{"乘胜追击", "速速茶点"} {
			t.Run(fmt.Sprintf("%d/%s", p, first), func(t *testing.T) {
				e := currentCardGame(t, p)
				auditPlay(t, e, p, first)
				second := "速速茶点"
				if first == second {
					second = "乘胜追击"
				}
				auditPlay(t, e, p, second)
				n := 3
				if first == "乘胜追击" {
					n = 2
				}
				for i := 0; i < n; i++ {
					auditPlay(t, e, p, "碌碌无为")
				}
				before := e.DiceTotal(p)
				snap := e.G.SnapshotPooled()
				defer engine.ReleaseSnap(snap)
				checkpoint, err := e.G.ExportCheckpoint()
				if err != nil {
					t.Fatal(err)
				}
				for attempt := 0; attempt < 3; attempt++ {
					if attempt == 1 {
						e.G.RestoreFromSnap(snap)
					}
					if attempt == 2 {
						if err := e.G.RestoreCheckpoint(checkpoint); err != nil {
							t.Fatal(err)
						}
					}
					auditSkill(t, e, p, "枪")
					want := 1
					if first == "乘胜追击" {
						want = 2
					}
					if e.DiceTotal(p) != before || e.counterByChar("速速茶点_buff", p, 0) != want {
						t.Fatal("FIFO order/unused charge not preserved")
					}
				}
				clone := e.RT.Clone()
				if !reflect.DeepEqual(clone.Game.Buffs, e.G.Buffs) {
					t.Fatal("clone lost instance order")
				}
				clone.Game.ResetDynamicState(1)
				if len(clone.Game.Buffs) != 0 || len(e.G.Buffs) == 0 {
					t.Fatal("reset leaked or mutated source")
				}
			})
		}
	}
}

func TestBuffInstances_LotusPrecedesWaterCloud(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, lotusFirst := range []bool{false, true} {
			t.Run(fmt.Sprintf("%d/%t", p, lotusFirst), func(t *testing.T) {
				e := currentCardGame(t, p, []string{"墨客", "赤蝶"}, []string{"赤蝶", "墨客"})
				if lotusFirst {
					auditPlay(t, e, p, "荷花酥")
				}
				auditSkill(t, e, p, "墨意")
				if !lotusFirst {
					auditPlay(t, e, p, "荷花酥")
				}
				hp := e.RT.Chars.BySlot[p][0].HPCounterID
				e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
					g.DealDamage(hp, engine.ElemPhysical, 3, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
				})
				if e.HP(p, 0) != 15 || e.counterByChar("水云", p, 0) != 2 || e.counterByChar("荷花酥_buff", p, 0) != 0 {
					t.Fatal("zeroing category must preserve ordinary reduction")
				}
			})
		}
	}
}

func TestBuffInstances_TeamInkSurvivesOwnerDeath(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p, []string{"墨客", "赤蝶"}, []string{"赤蝶", "墨客"})
			e.G.Counters[e.RT.Chars.BySlot[p][0].EnergyCounterID].Value = 2
			auditSkill(t, e, p, "水龙吟")
			hp := e.RT.Chars.BySlot[p][0].HPCounterID
			e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
				g.DealDamage(hp, engine.ElemPhysical, 15, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
			})
			e.G.Step(0)
			before := e.HP(1-p, 0)
			auditSkill(t, e, p, "枪")
			if e.HP(1-p, 0) != before-4 || e.G.ReadCounter(findCounterIDPerPlayer(e, "泼墨", p)) != 1 {
				t.Fatal("team effect was lost with its producer")
			}
		})
	}
}

func TestBuffInstances_DeathClearsMarkWithoutTransfer(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "蝶鳞")
			auditSkill(t, e, p, "枪")
			e.G.Counters[e.RT.Chars.BySlot[1-p][0].HPCounterID].Value = 1
			e.G.Turn = p
			if e.G.Step(e.FindAction(engine.ActionSkill, "枪")) != engine.StepNeedTarget {
				t.Fatal("expected death choice")
			}
			if e.counterByChar("蝶印", 1-p, 0) != 0 {
				t.Fatal("dead character retained mark")
			}
			e.G.Step(0)
			if e.counterByChar("蝶印", 1-p, 1) != 0 || e.HP(1-p, 1) != 15 {
				t.Fatal("mark transferred to replacement")
			}
		})
	}
}

func TestBuffInstances_SwordBonusOnlySkillDamage(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p, []string{"墨客", "赤蝶"}, []string{"墨客", "赤蝶"})
			auditPlay(t, e, p, "西风剑")
			hp := e.RT.Chars.BySlot[1-p][0].HPCounterID
			for _, source := range []engine.Source{engine.SrcCard, engine.SrcStatus, engine.SrcSummon, engine.SrcReaction, engine.SrcSupport} {
				e.G.ExecuteEffect(engine.EventFrame{Player: p, Char: 0, Source: source}, func(g *engine.Game) {
					g.DealDamage(hp, engine.ElemPhysical, 1, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
				})
				if e.counterByChar("西风剑_next_bonus", p, 1) != 0 {
					t.Fatalf("source %v generated skill-only bonus", source)
				}
			}
			auditSkill(t, e, p, "剑")
			if e.counterByChar("西风剑_next_bonus", p, 1) != 1 {
				t.Fatal("skill did not generate bonus")
			}
		})
	}
}
