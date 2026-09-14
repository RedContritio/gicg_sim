package engine

func (g *Game) EnterSupport(player, ref int) {
	if len(g.Players[player].Supports) >= MaxSupportSlots {
		panic("support zone full at entry")
	}
	g.Players[player].Supports = append(g.Players[player].Supports,
		SupportInst{ID: g.nextEffectIdentity(), Ref: ref, ActivatedAt: g.Round})
}

func (g *Game) RemoveSupportAt(player, slot int) {
	p := &g.Players[player]
	if slot < 0 || slot >= len(p.Supports) {
		panic("invalid support slot")
	}
	support := p.Supports[slot]
	p.Supports = append(p.Supports[:slot], p.Supports[slot+1:]...)
	if support.BuffID != 0 {
		g.RemoveBuff(support.BuffID)
	}
	p.Discard = append(p.Discard, CardInst{Ref: support.Ref, DrawnAtRound: g.Round})
	g.FireEventHooks(HookSupportRemove, &EventContext{ActorPlayer: player, CardRef: support.Ref})
}

func (g *Game) RemoveSupportByID(player int, id uint64) {
	if id == 0 {
		panic("support replacement requires a lifecycle identity")
	}
	for slot, support := range g.Players[player].Supports {
		if support.ID == id {
			g.RemoveSupportAt(player, slot)
			return
		}
	}
	// A payment-triggered effect may already have removed the chosen support.
}

func (g *Game) enumerateSupportReplacement(pi, hand int, base *EventContext, payments [][DiceColorCount]int8, actions []Action) []Action {
	for slot := range g.Players[pi].Supports {
		for _, payment := range payments {
			actions = append(actions, Action{Kind: ActionCard, PlayerIdx: pi, Index: hand,
				DicePayment: payment, AppliedMods: base.AppliedMods, HasSupportTarget: true,
				TargetPlayer: pi, TargetChar: -1, TargetSupport: slot})
		}
	}
	return actions
}
