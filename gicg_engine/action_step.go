package engine

// Step dispatch + pending-target resolution — the Step/StepTarget
// entry points plus the forced-switch / card-target pending flows.

func (g *Game) Step(actionIdx int) StepResult {
	g.RequireHealthy()
	if g.resume != nil && g.executing == nil {
		return g.resumeTarget(actionIdx)
	}
	return g.runBoundary(boundaryOperation{kind: boundaryStep, index: actionIdx})
}

func (g *Game) step(actionIdx int) StepResult {
	g.RequireHealthy()
	if g.Phase == PhaseGameOver {
		return StepGameOver
	}
	if g.PendingCardTarget != nil {
		return g.resolveCardTarget(actionIdx)
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

	g.logAction(action)

	switch action.Kind {
	case ActionSkill:
		return g.executeSkill(action)
	case ActionCard:
		return g.executeCard(action)
	case ActionSwitch:
		if !action.Forced && g.executing != nil {
			g.executing.public = publicCause{CauseSwitch, action.PlayerIdx, g.Players[action.PlayerIdx].ActiveChar,
				-1, action.PlayerIdx, action.Index, 0}
		}
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
	g.RequireHealthy()
	if g.resume != nil && g.executing == nil {
		return g.resumeTarget(targetIdx)
	}
	return g.runBoundary(boundaryOperation{kind: boundaryTarget, index: targetIdx})
}

func (g *Game) stepTarget(targetIdx int) StepResult {
	g.RequireHealthy()
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
	g.PendingAction = nil
	charIdx := targets[targetIdx]
	g.logAction(Action{Kind: ActionSwitch, PlayerIdx: pi, Index: charIdx, Forced: pending.Forced})

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
	g.DrainDeferred()
	g.PopEvent()

	if g.Phase == PhaseGameOver {
		return StepGameOver
	}
	return StepContinue
}

func (g *Game) cardTargetActions(pc *PendingCard) []Action {
	pc.validate(g)
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
			AppliedMods:  pc.AppliedMods,
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
	return g.PendingCardTarget.Resume(g, targetIdx)
}
