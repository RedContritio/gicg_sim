package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// --- helpers specific to talent card tests ---

// playCard finds a card in the current player's hand by name and plays it,
// handling any pending target selection. Returns false if the card isn't
// currently a legal action.
func (env *GameEnv) playCard(t *testing.T, name string) bool {
	t.Helper()
	idx := env.FindAction(engine.ActionCard, name)
	if idx < 0 {
		return false
	}
	env.Step(idx)
	return true
}

// playToRoundEnd advances both players through EndTurn until round increments.
func (env *GameEnv) playToRoundEnd(t *testing.T) {
	t.Helper()
	startRound := env.G.Round
	for i := 0; i < 40 && env.G.Round == startRound; i++ {
		if env.G.Phase == engine.PhaseGameOver {
			return
		}
		// Just spam EndTurn for whoever's turn it is.
		if !env.endTurnIfPossible() {
			env.Step(0)
		}
	}
}

func (env *GameEnv) endTurnIfPossible() bool {
	idx := env.FindAction(engine.ActionEndTurn, "")
	if idx < 0 {
		return false
	}
	env.Step(idx)
	return true
}
