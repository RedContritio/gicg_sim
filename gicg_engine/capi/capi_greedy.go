package main

// Greedy F1-D2 opponent fast path: expose the Go-native greedy search
// (full port in gicg_actor/dmc/greedy_player.go) to Python via one cgo
// call per decision. Python's GreedyPlayer delegates select_action here
// when dice_greedy=True (the Go port always folds the dice-payment
// fan-out; dice_greedy=False semantics stay on the Python path).
//
// Equivalence gate (per the Go port's design D2): winrate equivalence
// within 95% CI, NOT move-by-move identity — D2-D4 minimax accumulates
// floating-point eps that can flip exact ties. Python side keeps
// select_with_info pure-Python for BC tools that need scored lists.

import "C"

import (
	dmc "gicg_mono/gicg_actor/dmc"
)

//export GameSelectGreedyAction
func GameSelectGreedyAction(id C.int, features *C.char, depth C.int, budget C.int, seed C.longlong) (ret C.int) {
	defer recoverRuleErrorInt(id, &ret)
	h := getHandle(int(id))
	if h == nil || h.RT == nil {
		return -1
	}
	gp, err := dmc.NewGreedyPlayer(C.GoString(features), int(depth), int64(seed), int(budget))
	if err != nil {
		return -1
	}
	action, err := gp.SelectAction(h.RT)
	if err != nil {
		return -1
	}
	return C.int(action)
}
