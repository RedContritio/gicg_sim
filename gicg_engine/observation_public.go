package engine

// Public decision state must remain visible even if there are no buff rows.
// Existing first three meta fields retain their positions.
func (g *Game) writePublicMeta(obs []int32, perspective int) {
	// Explicit observer: Turn may differ during forced-switch decisions.
	obs[18] = int32(perspective)
	obs[0], obs[1] = int32(g.Phase), int32(g.Round)
	obs[2] = boolToInt32(g.Turn == perspective)
	obs[3] = boolToInt32(g.Players[perspective].DeclaredEnd)
	obs[4] = boolToInt32(g.Players[1-perspective].DeclaredEnd)
	obs[5] = relativePlayer(g.FirstEnd, perspective)
	obs[6] = int32(g.MaxRounds)
	// 0 ordinary; otherwise action kind + 1. Target selection for a played
	// card uses ActionCard + 1. Current training cards use joint target actions.
	if g.PendingDice != nil {
		obs[7] = int32(ActionReroll) + 1
	} else if g.PendingAction != nil {
		obs[7] = int32(g.PendingAction.Kind) + 1
		obs[8] = boolToInt32(g.PendingAction.Forced)
	} else if g.PendingCardTarget != nil {
		obs[7] = int32(ActionCard) + 1
	}
	if len(g.FixDice) == DiceColorCount {
		obs[9] = 1
		for i, v := range g.FixDice {
			obs[10+i] = int32(v)
		}
	}
}
