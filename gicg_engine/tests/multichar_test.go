package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestMulti_2v2_GameStarts(t *testing.T) {
	env := NewGame(t, []string{"赤蝶", "墨客"}, []string{"猫咪", "刻师傅"})

	if env.G.Phase != engine.PhaseAction {
		t.Fatalf("expected PhaseAction, got %d", env.G.Phase)
	}

	// All 4 chars should be alive
	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < 2; ci++ {
			if !env.Alive(pi, ci) {
				t.Errorf("P%dC%d should be alive", pi, ci)
			}
			if env.HP(pi, ci) <= 0 {
				t.Errorf("P%dC%d HP should be positive, got %d", pi, ci, env.HP(pi, ci))
			}
		}
	}

	// Both teams should have 2 chars
	if len(env.G.Players[0].Chars) != 2 || len(env.G.Players[1].Chars) != 2 {
		t.Errorf("expected 2 chars each, got %d and %d",
			len(env.G.Players[0].Chars), len(env.G.Players[1].Chars))
	}
}

func TestMulti_2v2_GameEnds(t *testing.T) {
	cases := []struct {
		name  string
		team0 []string
		team1 []string
	}{
		{"赤墨_vs_猫刻", []string{"赤蝶", "墨客"}, []string{"猫咪", "刻师傅"}},
		{"天猫_vs_赤刻", []string{"天星", "猫咪"}, []string{"赤蝶", "刻师傅"}},
		{"墨刻_vs_天赤", []string{"墨客", "刻师傅"}, []string{"天星", "赤蝶"}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			env := NewGame(t, tc.team0, tc.team1)
			env.G.Log = engine.NewEventLog()
			env.PlayToEnd(1000)

			var damages, deaths int
			for _, e := range env.G.Log.Entries {
				if e.Type == "damage" {
					damages++
				}
				if e.Type == "death" {
					deaths++
				}
			}

			t.Logf("phase=%d winner=%d rounds=%d damages=%d deaths=%d",
				env.G.Phase, env.G.Winner, env.G.Round, damages, deaths)

			if env.G.Phase != engine.PhaseGameOver {
				t.Errorf("game didn't end")
			}
			if deaths < 2 {
				t.Logf("WARN: expected at least 2 deaths in 2v2, got %d", deaths)
			}
		})
	}
}

func TestMulti_3v3_GameStarts(t *testing.T) {
	env := NewGame(t,
		[]string{"赤蝶", "墨客", "猫咪"},
		[]string{"刻师傅", "天星", "赤蝶"},
	)

	if env.G.Phase != engine.PhaseAction {
		t.Fatalf("expected PhaseAction, got %d", env.G.Phase)
	}

	// All 6 chars alive
	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < 3; ci++ {
			if !env.Alive(pi, ci) {
				t.Errorf("P%dC%d should be alive", pi, ci)
			}
		}
	}
}

func TestMulti_3v3_GameEnds(t *testing.T) {
	env := NewGame(t,
		[]string{"赤蝶", "墨客", "猫咪"},
		[]string{"刻师傅", "天星", "赤蝶"},
	)
	env.G.Log = engine.NewEventLog()
	env.PlayToEnd(2000)

	var deaths int
	for _, e := range env.G.Log.Entries {
		if e.Type == "death" {
			deaths++
		}
	}

	t.Logf("phase=%d winner=%d rounds=%d deaths=%d",
		env.G.Phase, env.G.Winner, env.G.Round, deaths)

	if env.G.Phase != engine.PhaseGameOver {
		t.Errorf("3v3 game didn't end in 2000 steps")
	}
}
