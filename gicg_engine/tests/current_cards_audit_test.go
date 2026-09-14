package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
)

// Use the production loader and just the two pools referenced by live configs.
// Setups are explicit; opponent actions never introduce incidental reactions.
func currentCardGame(t *testing.T, owner int, teams ...[]string) *GameEnv {
	t.Helper()
	cfg := factory.GameConfig{DataDir: dataDir, Pools: []string{"v_legacy", "test_basic"}, Seed: 42}
	cfg.Players[owner] = factory.PConfig{Chars: []factory.CharDef{{Name: "赤蝶"}, {Name: "墨客"}}, Deck: []string{"碌碌无为"}}
	cfg.Players[1-owner] = factory.PConfig{Chars: []factory.CharDef{{Name: "墨客"}, {Name: "赤蝶"}}, Deck: []string{"碌碌无为"}}
	if len(teams) == 2 {
		for i, names := range teams {
			p := owner
			if i == 1 {
				p = 1 - owner
			}
			cfg.Players[p].Chars = nil
			for _, name := range names {
				cfg.Players[p].Chars = append(cfg.Players[p].Chars, factory.CharDef{Name: name})
			}
		}
	}
	h, err := factory.NewGame(cfg)
	if err != nil {
		t.Fatal(err)
	}
	h.Game.Step(0)
	h.Game.Step(0)
	h.Game.GetLegalActions()
	h.Game.Players[0].Hand = nil
	h.Game.Players[1].Hand = nil
	h.Game.Turn = owner
	env := &GameEnv{G: h.Game, RT: h.RT, T: t}
	env.SetDice(owner, map[int]int{engine.DiceColorOmni: 16})
	return env
}

func auditPlay(t *testing.T, env *GameEnv, p int, name string) {
	t.Helper()
	env.G.Turn = p
	env.giveCard(t, p, name)
	idx := env.FindAction(engine.ActionCard, name)
	if idx < 0 {
		t.Fatalf("%s unavailable for P%d", name, p)
	}
	if got := env.G.Step(idx); got == engine.StepNeedTarget {
		t.Fatalf("%s unexpectedly needs another target", name)
	}
}

func TestCurrentCards_ImmediateEffectsBothSeats(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, name := range []string{"碌碌无为", "美味烧鸡", "占星", "诅咒", "佛跳墙", "荷花酥", "速速茶点", "反制", "测试卡_碎片", "测试卡_增幅", "测试卡_神秘水流"} {
			t.Run(fmt.Sprintf("P%d/%s", p, name), func(t *testing.T) {
				e := currentCardGame(t, p)
				own, enemy := e.RT.Chars.BySlot[p][0], e.RT.Chars.BySlot[1-p][0]
				e.G.Counters[own.HPCounterID].Value = 8
				e.G.Counters[enemy.EnergyCounterID].Value = 2
				cost := map[string]int{"碌碌无为": 1, "美味烧鸡": 1, "占星": 2, "诅咒": 2, "佛跳墙": 2, "荷花酥": 2, "速速茶点": 1, "反制": 2, "测试卡_碎片": 1, "测试卡_增幅": 2, "测试卡_神秘水流": 2}[name]
				before := e.DiceTotal(p)
				auditPlay(t, e, p, name)
				if got := before - e.DiceTotal(p); got != cost {
					t.Errorf("payment=%d want %d", got, cost)
				}
				if e.G.Turn != p {
					t.Error("fast card changed turn")
				}
				if e.countHandCard(p, name) != 0 {
					t.Error("played card still in hand")
				}
				wantHP, wantEnemyHP := 8, 15
				switch name {
				case "美味烧鸡":
					wantHP = 9
				case "占星":
					if e.Energy(p, 0) != 2 {
						t.Error("expected +2 energy")
					}
				case "诅咒":
					if e.Energy(1-p, 0) != 1 {
						t.Error("expected -1 enemy energy")
					}
				case "佛跳墙", "荷花酥", "速速茶点":
					want := 1
					if name == "速速茶点" {
						want = 2
					}
					if e.counterByChar(name+"_buff", p, 0) != want {
						t.Error("wrong food buff")
					}
				case "反制":
					if e.counterByChar("反制_debuff", 1-p, 0) != 1 {
						t.Error("wrong enemy debuff")
					}
				case "测试卡_碎片":
					wantEnemyHP = 14
				case "测试卡_神秘水流":
					wantEnemyHP = 13
				case "测试卡_增幅":
					if e.G.Counters[findCounterIDPerPlayer(e, "测试卡_增幅_buff", p)].Value != 1 {
						t.Error("missing amplification")
					}
				}
				if e.HP(p, 0) != wantHP || e.HP(1-p, 0) != wantEnemyHP {
					t.Fatalf("HP own/enemy=%d/%d want %d/%d", e.HP(p, 0), e.HP(1-p, 0), wantHP, wantEnemyHP)
				}
				if name == "美味烧鸡" || name == "佛跳墙" || name == "荷花酥" || name == "速速茶点" {
					if e.counterByChar("饱腹", p, 0) != 1 {
						t.Error("food did not set satiety")
					}
				}
			})
		}
	}
}

func TestCurrentCards_DieLinBurstTriggersOnce(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprint(p), func(t *testing.T) {
			e := currentCardGame(t, p)
			auditPlay(t, e, p, "蝶鳞")
			e.G.Turn = p
			if !e.StepSkill("枪") {
				t.Fatal("normal unavailable")
			}
			// The marked target took 4 infused damage; burst must add exactly 4+1.
			before := e.HP(1-p, 0)
			e.G.Counters[e.RT.Chars.BySlot[p][0].EnergyCounterID].Value = 3
			e.G.Turn = p
			if !e.StepSkill("回火") {
				t.Fatal("burst unavailable")
			}
			if got := before - e.HP(1-p, 0); got != 5 {
				t.Fatalf("burst damage=%d want 5 (one extra hit)", got)
			}
		})
	}
}
