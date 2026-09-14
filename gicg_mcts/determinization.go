package mcts

// Determinization carries one pre-sampled hidden-state assignment
// for the opponent. Python's CardPoolSpec samples these before
// entering Go. Go applies via SetPlayerHand/Deck/Dice at the
// start of each rollout.
type Determinization struct {
	Opponent int32
	Hand     []int32
	Deck     []int32
	Dice     []int32
}
