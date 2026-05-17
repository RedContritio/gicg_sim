package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestBasic_GameStarts(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	if env.G.Phase != engine.PhaseAction {
		t.Fatalf("expected PhaseAction, got %d", env.G.Phase)
	}
	if env.HP(0, 0) <= 0 || env.HP(1, 0) <= 0 {
		t.Fatalf("initial HP should be positive: P0=%d, P1=%d", env.HP(0, 0), env.HP(1, 0))
	}
	if env.DiceTotal(0) != 8 || env.DiceTotal(1) != 8 {
		t.Errorf("initial dice pool should total 8: P0=%d, P1=%d", env.DiceTotal(0), env.DiceTotal(1))
	}
}

func TestBasic_SkillsRegistered(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"猫咪"})
	// 赤蝶 should have 枪, 蝶火, 回火
	for _, name := range []string{"枪", "蝶火", "回火"} {
		if env.SkillID("赤蝶", name) < 0 {
			t.Errorf("赤蝶 missing skill %s", name)
		}
	}
	// 猫咪 should have 箭, 猫爪护盾, 甜美领域
	for _, name := range []string{"箭", "猫爪护盾", "甜美领域"} {
		if env.SkillID("猫咪", name) < 0 {
			t.Errorf("猫咪 missing skill %s", name)
		}
	}
}

func TestBasic_CardsLoaded(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	if len(env.G.CardNames) == 0 {
		t.Error("no cards loaded")
	}
	// L1-L3 should have at least: 碌碌无为, 以牙还牙, 铁剑
	for _, name := range []string{"碌碌无为", "以牙还牙"} {
		found := false
		for _, n := range env.G.CardNames {
			if n == name {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("missing card %s", name)
		}
	}
}

func TestBasic_AllCharPairs(t *testing.T) {
	chars := []string{"赤蝶", "墨客", "猫咪", "刻师傅", "天星"}
	for _, c0 := range chars {
		for _, c1 := range chars {
			if c0 == c1 {
				continue
			}
			t.Run(c0+"_vs_"+c1, func(t *testing.T) {
				env := NewGame(t, []string{c0}, []string{c1})
				if env.G.Phase != engine.PhaseAction {
					t.Fatalf("game didn't start")
				}
				if env.HP(0, 0) <= 0 || env.HP(1, 0) <= 0 {
					t.Fatalf("invalid HP: %d vs %d", env.HP(0, 0), env.HP(1, 0))
				}
			})
		}
	}
}
