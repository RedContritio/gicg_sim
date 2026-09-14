package mcts

import "math"

// PUCTScore computes the PUCT score for one child, from parent.turn's
// perspective. Mirrors training/mcts.py::_puct_select inner loop:
//
//	q_p0 = child.q_p0()
//	q = q_p0 if parent.turn == 0 else -q_p0
//	u = c_puct · P · sqrt(N_avail) / (1 + N_total)
//	score = q + u
//
// where N_total = N + N_virtual (virtual loss biases score toward
// less-explored children during concurrent descents).
func PUCTScore(child *Node, parentTurn int8, cPuct float32) float32 {
	n := child.N.Load()
	vl := int64(child.NVirtual.Load())
	total := n + vl
	nAvail := int32(child.NAvail.Load())

	qP0 := child.QP0()
	var q float32
	if parentTurn == 0 {
		q = qP0
	} else {
		q = -qP0
	}

	u := cPuct * child.Prior * float32(math.Sqrt(float64(nAvail))) / float32(1+total)
	return q + u
}

// SelectChild picks the best child index by PUCT score among
// currently-legal actions (legalMask[i] == true means action[i] is
// legal under this rollout's determinization).
//
// Tie-break: lexicographically-smaller ActionId wins (matches
// Python's `aid < best_id` secondary key, preserving determinism
// across runs with identical seed).
//
// Preconditions:
//   - node.Expanded.Load() == true (children/actions installed)
//   - len(legalMask) == node.NumLegalActions()
//   - at least one entry in legalMask is true (caller checks terminal)
//
// Returns the index i such that node.children[i] is the selected
// child (pool index). Panics if no legal child found — that's a
// caller bug (terminal state reached without detection).
func SelectChild(pool *Pool, node *Node, legalMask []bool, cPuct float32) int32 {
	return selectChildWithTurn(pool, node, legalMask, cPuct, node.Turn)
}

func selectChildWithTurn(pool *Pool, node *Node, legalMask []bool, cPuct float32, turn int8) int32 {
	children := node.children
	actions := node.actions

	bestIdx := int32(-1)
	var bestScore float32
	var bestAction ActionId

	for i := 0; i < len(legalMask); i++ {
		if !legalMask[i] {
			continue
		}
		child := pool.Get(children[i])
		score := PUCTScore(child, turn, cPuct)
		action := actions[i]

		if bestIdx == -1 ||
			score > bestScore ||
			(score == bestScore && action.Less(bestAction)) {
			bestIdx = int32(i)
			bestScore = score
			bestAction = action
		}
	}

	if bestIdx == -1 {
		panic("mcts: SelectChild called with no legal children (all legalMask == false)")
	}
	return bestIdx
}
