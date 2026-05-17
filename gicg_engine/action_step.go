package engine

// Step dispatch + pending-target resolution — the Step/StepTarget
// entry points plus the forced-switch / card-target pending flows.

func (g *Game) Step(actionIdx int) StepResult {
	if g.Phase == PhaseGameOver {
		return StepGameOver
	}

	// 回合间暂停：自动推进到下一回合
	if g.Phase == PhaseRoundStart {
		g.NewRound()
	}

	actions := g.GetLegalActions()
	if actionIdx < 0 || actionIdx >= len(actions) {
		return StepContinue
	}
	action := actions[actionIdx]

	// 首回合选人：直接设 ActiveChar，然后轮到下一个玩家或进入回合
	if g.Phase == PhaseSelectActive {
		return g.executeSelectActive(action)
	}

	// Log action
	if g.Log != nil {
		g.Log.NextStep()
		pi := action.PlayerIdx
		ci := g.Players[pi].ActiveChar
		switch action.Kind {
		case ActionSkill:
			g.Log.Append(g, "action_skill", pi, ci, map[string]interface{}{"skill_id": action.Index})
		case ActionCard:
			ref := -1
			if action.Index < len(g.Players[pi].Hand) {
				ref = g.Players[pi].Hand[action.Index].Ref
			}
			g.Log.Append(g, "action_card", pi, ci, map[string]interface{}{"card_ref": ref, "hand_idx": action.Index})
		case ActionSwitch:
			g.Log.Append(g, "action_switch", pi, ci, map[string]interface{}{"target_char": action.Index})
		case ActionEndTurn:
			g.Log.Append(g, "action_end_turn", pi, ci, nil)
		}
	}

	switch action.Kind {
	case ActionSkill:
		return g.executeSkill(action)
	case ActionCard:
		return g.executeCard(action)
	case ActionSwitch:
		actCtx := ActSwitch
		if action.Forced {
			g.PendingAction = nil
			actCtx = ActForcedDeath
		}
		return g.executeSwitch(action, actCtx)
	case ActionEndTurn:
		return g.executeEndTurn(action)
	case ActionTune:
		return g.executeTune(action)
	}
	return StepContinue
}

func (g *Game) StepTarget(targetIdx int) StepResult {
	if g.Phase == PhaseGameOver {
		return StepGameOver
	}

	if g.PendingCardTarget != nil {
		return g.resolveCardTarget(targetIdx)
	}

	if g.PendingAction != nil {
		return g.resolveSwitchTarget(targetIdx)
	}

	return StepContinue
}

func (g *Game) resolveSwitchTarget(targetIdx int) StepResult {
	pending := g.PendingAction
	g.PendingAction = nil

	pi := pending.PlayerIdx
	p := &g.Players[pi]

	var targets []int
	for k, ch := range p.Chars {
		if k == p.ActiveChar || !ch.Alive {
			continue
		}
		targets = append(targets, k)
	}
	if targetIdx < 0 || targetIdx >= len(targets) {
		return StepContinue
	}
	charIdx := targets[targetIdx]

	actCtx := ActSwitch
	if pending.Forced {
		actCtx = ActForcedDeath
	}

	g.PushEvent(EventFrame{
		ActionCtx: actCtx,
		Source:    SrcNone,
		Player:    pi,
		Char:      p.ActiveChar,
	})

	p.ActiveChar = charIdx

	ctx := &EventContext{
		ActionCtx:   actCtx,
		ActorPlayer: pi,
		ActorChar:   charIdx,
	}
	g.FireEventHooks(HookSwitch, ctx)
	g.PopEvent()

	if g.Phase == PhaseGameOver {
		return StepGameOver
	}
	return StepContinue
}

func (g *Game) cardTargetActions(pc *PendingCard) []Action {
	var targetPlayerIdx int
	if pc.TargetMode == 1 {
		targetPlayerIdx = pc.PlayerIdx
	} else {
		targetPlayerIdx = 1 - pc.PlayerIdx
	}

	var actions []Action
	for k := range g.Players[targetPlayerIdx].Chars {
		ctx := &EventContext{
			Playable:     true,
			ActionKind:   ActionCard,
			ActionCtx:    ActPlayCard,
			ActorPlayer:  pc.PlayerIdx,
			ActorChar:    g.Players[pc.PlayerIdx].ActiveChar,
			CardRef:      pc.CardRef,
			TargetPlayer: targetPlayerIdx,
			TargetChar:   k,
		}
		g.FireEventHooks(HookActionCheck, ctx)
		if ctx.Playable {
			actions = append(actions, Action{
				Kind:      ActionCard,
				PlayerIdx: targetPlayerIdx,
				Index:     k,
				Forced:    true,
			})
		}
	}
	return actions
}

func (g *Game) resolveCardTarget(targetIdx int) StepResult {
	pc := g.PendingCardTarget
	g.PendingCardTarget = nil

	targets := g.cardTargetActions(pc)
	if targetIdx < 0 || targetIdx >= len(targets) {
		return StepContinue
	}
	chosen := targets[targetIdx]

	// Attach target info to the most recent action_card log entry
	if g.Log != nil {
		for i := len(g.Log.Entries) - 1; i >= 0; i-- {
			if g.Log.Entries[i].Type == "action_card" {
				g.Log.Entries[i].Fields["target_player"] = chosen.PlayerIdx
				g.Log.Entries[i].Fields["target_char"] = chosen.Index
				break
			}
		}
	}

	return g.resolveCard(pc.PlayerIdx, pc.CardRef, pc.BattleAction, chosen.PlayerIdx, chosen.Index)
}

// executeSkill 执行技能动作
