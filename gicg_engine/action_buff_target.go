package engine

func (g *Game) enumerateBuffCards(pi, hand, cardRef int, base *EventContext, payments [][DiceColorCount]int8, actions []Action) []Action {
	for position, buff := range g.Buffs {
		def := g.BuffDefinitions[buff.Definition]
		owner := g.GetCounterChar(def.CounterID)[0]
		if !def.Summon || owner != 1-pi {
			continue
		}
		ctx := *base
		ctx.TargetPlayer, ctx.TargetChar, ctx.TargetBuffID = owner, -1, buff.ID
		g.FireEventHooks(HookActionCheck, &ctx)
		if !ctx.Playable {
			continue
		}
		for _, payment := range payments {
			actions = append(actions, Action{Kind: ActionCard, PlayerIdx: pi, Index: hand,
				DicePayment: payment, AppliedMods: base.AppliedMods, HasBuffTarget: true,
				TargetPlayer: owner, TargetChar: -1, TargetBuff: position})
		}
	}
	return actions
}

// SelectedBuffCounter returns a definition and storage mode without exposing
// lifecycle IDs to the DSL. A target removed during payment resolves to null.
func (g *Game) SelectedBuffCounter(id uint64) (int, bool) {
	if b := g.buffByID(id); b != nil {
		return g.BuffDefinitions[b.Definition].CounterID, b.Independent
	}
	return -1, false
}
