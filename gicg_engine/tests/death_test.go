package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestDeath_CharDies(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.G.Log = engine.NewEventLog()
	env.PlayToEnd(500)

	if env.G.Phase != engine.PhaseGameOver {
		t.Fatal("game should end with a death")
	}

	// Winner's opponent should be dead
	loser := 1 - env.G.Winner
	if env.Alive(loser, 0) {
		t.Errorf("P%d char should be dead", loser)
	}
	if env.HP(loser, 0) > 0 {
		t.Errorf("P%d HP should be 0, got %d", loser, env.HP(loser, 0))
	}

	// Winner should be alive
	if !env.Alive(env.G.Winner, 0) {
		t.Error("winner should be alive")
	}

	// Check death event in log
	var deathEvents int
	for _, e := range env.G.Log.Entries {
		if e.Type == "death" {
			deathEvents++
		}
	}
	if deathEvents != 1 {
		t.Errorf("expected 1 death event, got %d", deathEvents)
	}
}

func TestDeath_WinnerLogged(t *testing.T) {
	env := NewGame(t, []string{"刻师傅"}, []string{"赤蝶"})
	env.G.Log = engine.NewEventLog()
	env.PlayToEnd(500)

	var winnerLogged bool
	for _, e := range env.G.Log.Entries {
		if e.Type == "winner" {
			winnerLogged = true
			w := e.Fields["winner"].(int)
			if w != env.G.Winner {
				t.Errorf("log winner=%d != game winner=%d", w, env.G.Winner)
			}
		}
	}
	if !winnerLogged {
		t.Error("winner event not in log")
	}
}
