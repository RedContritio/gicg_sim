package engine

// Per-candidate-kind legal-action enumeration helpers. The entry point
// GetLegalActions lives in action.go and composes these.

// enumerateSkills appends legal skill actions for the active char of
// player pi to actions, consulting ActionPrepare/Check hooks and
// EnumerateCostPayments over pool.
func (g *Game) enumerateSkills(pi int, pool [DiceColorCount]int, rt DicePoolProvider, actions []Action) []Action {
	p := &g.Players[pi]
	active := &p.Chars[p.ActiveChar]
	if !active.Alive {
		return actions
	}
	for _, skillID := range active.Skills {
		cost, ok := rt.SkillCost(skillID)
		if !ok {
			continue
		}
		ctx := &EventContext{
			Playable:      true,
			ActionKind:    ActionSkill,
			ActorPlayer:   pi,
			ActorChar:     p.ActiveChar,
			SkillIndex:    skillID,
			CardRef:       FilterAny,
			TargetPlayer:  FilterAny,
			TargetChar:    FilterAny,
			Cost:          cost.Dices,
			CurrentHookID: -1,
		}
		g.FireEventHooks(HookActionPrepare, ctx)
		g.FireEventHooks(HookActionCheck, ctx)
		if !ctx.Playable {
			continue
		}
		ctx.Cost.Clamp()
		payments := EnumerateCostPayments(pool, ctx.Cost)
		for _, payment := range payments {
			actions = append(actions, Action{
				Kind:        ActionSkill,
				PlayerIdx:   pi,
				Index:       skillID,
				DicePayment: payment,
				AppliedMods: ctx.AppliedMods,
			})
		}
	}
	return actions
}

// enumerateCards appends legal card actions (including joint target ×
// payment fan-out) for player pi to actions.
func (g *Game) enumerateCards(pi int, pool [DiceColorCount]int, rt DicePoolProvider, actions []Action) []Action {
	p := &g.Players[pi]
	for j := range p.Hand {
		cardRef := p.Hand[j].Ref
		cost, ok := rt.CardCost(cardRef)
		if !ok {
			continue
		}
		ctx := &EventContext{
			Playable:      true,
			ActionKind:    ActionCard,
			ActorPlayer:   pi,
			ActorChar:     p.ActiveChar,
			SkillIndex:    j,
			HandIndex:     j,
			CardRef:       cardRef,
			TargetPlayer:  FilterAny,
			TargetChar:    FilterAny,
			Cost:          cost.Dices,
			CurrentHookID: -1,
		}
		g.FireEventHooks(HookActionPrepare, ctx)
		g.FireEventHooks(HookActionCheck, ctx)
		if !ctx.Playable {
			continue
		}
		ctx.Cost.Clamp()
		payments := EnumerateCostPayments(pool, ctx.Cost)
		if len(payments) == 0 {
			continue
		}
		if ctx.NeedTarget && ctx.TargetMode > 0 {
			if ctx.TargetMode == 4 {
				actions = g.enumerateSupportReplacement(pi, j, ctx, payments, actions)
				continue
			}
			if ctx.TargetMode == 3 {
				actions = g.enumerateBuffCards(pi, j, cardRef, ctx, payments, actions)
				continue
			}
			// Joint compound action: enumerate (target × payment).
			pc := &PendingCard{
				PlayerIdx:    pi,
				CardRef:      cardRef,
				BattleAction: ctx.BattleAction,
				TargetMode:   ctx.TargetMode,
				AppliedMods:  ctx.AppliedMods,
			}
			targets := g.cardTargetActions(pc)
			for _, t := range targets {
				for _, payment := range payments {
					actions = append(actions, Action{
						Kind:         ActionCard,
						PlayerIdx:    pi,
						Index:        j,
						DicePayment:  payment,
						AppliedMods:  ctx.AppliedMods,
						HasTarget:    true,
						TargetPlayer: t.PlayerIdx,
						TargetChar:   t.Index,
					})
				}
			}
		} else {
			for _, payment := range payments {
				actions = append(actions, Action{
					Kind:        ActionCard,
					PlayerIdx:   pi,
					Index:       j,
					DicePayment: payment,
					AppliedMods: ctx.AppliedMods,
				})
			}
		}
	}
	return actions
}

// enumerateSwitches appends voluntary switch actions (cost 1 any,
// possibly reduced by cost_mod hooks) for player pi.
func (g *Game) enumerateSwitches(pi int, pool [DiceColorCount]int, actions []Action) []Action {
	p := &g.Players[pi]
	for k, ch := range p.Chars {
		if k == p.ActiveChar || !ch.Alive {
			continue
		}
		ctx := &EventContext{
			Playable:      true,
			ActionKind:    ActionSwitch,
			ActorPlayer:   pi,
			ActorChar:     p.ActiveChar,
			SwitchChar:    k,
			CardRef:       FilterAny,
			TargetPlayer:  FilterAny,
			TargetChar:    FilterAny,
			Cost:          DiceCost{Any: 1},
			CurrentHookID: -1,
		}
		g.FireEventHooks(HookActionPrepare, ctx)
		g.FireEventHooks(HookActionCheck, ctx)
		if !ctx.Playable {
			continue
		}
		ctx.Cost.Clamp()
		switchPayments := EnumerateCostPayments(pool, ctx.Cost)
		for _, payment := range switchPayments {
			actions = append(actions, Action{
				Kind:        ActionSwitch,
				PlayerIdx:   pi,
				Index:       k,
				DicePayment: payment,
				AppliedMods: ctx.AppliedMods,
			})
		}
	}
	return actions
}

// enumerateTunes appends tune actions (discard 1 hand card → convert
// 1 non-active-element non-omni die to active-char color) for pi.
func (g *Game) enumerateTunes(pi int, pool [DiceColorCount]int, actions []Action) []Action {
	p := &g.Players[pi]
	active := &p.Chars[p.ActiveChar]
	if !active.Alive || len(p.Hand) == 0 {
		return actions
	}
	activeElemColor := ElementToDiceColor(active.Element)
	if activeElemColor < 0 {
		return actions
	}
	for c := 0; c < 7; c++ {
		if c == activeElemColor {
			continue
		}
		if pool[c] <= 0 {
			continue
		}
		for j := range p.Hand {
			actions = append(actions, Action{
				Kind:            ActionTune,
				PlayerIdx:       pi,
				Index:           j,
				TuneSourceColor: c,
			})
		}
	}
	return actions
}

// selectActiveActions 首回合选择出战角色（所有存活角色可选）
func (g *Game) selectActiveActions(playerIdx int) []Action {
	p := &g.Players[playerIdx]
	var actions []Action
	for k, ch := range p.Chars {
		if !ch.Alive {
			continue
		}
		actions = append(actions, Action{
			Kind:      ActionSwitch,
			PlayerIdx: playerIdx,
			Index:     k,
			Forced:    true, // 不消耗 AP，不触发切换 hook
		})
	}
	return actions
}

func (g *Game) forcedSwitchActions(playerIdx int) []Action {
	p := &g.Players[playerIdx]
	var actions []Action
	for k, ch := range p.Chars {
		if k == p.ActiveChar || !ch.Alive {
			continue
		}
		actions = append(actions, Action{
			Kind:      ActionSwitch,
			PlayerIdx: playerIdx,
			Index:     k,
			Forced:    true,
		})
	}
	return actions
}
