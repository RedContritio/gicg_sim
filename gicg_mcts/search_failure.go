package mcts

import engine "gicg_mono/gicg_engine"

type searchFailure struct{ err error }

func recoverRolloutFailure(err *error) {
	if v := recover(); v != nil {
		failure, ok := v.(*engine.RuleError)
		if !ok {
			panic(v)
		}
		*err = failure
	}
}
