package engine

// executeSkill / executeCard. Other action kinds (switch, end_turn,
// select_active, tune) plus shared helpers (PayDice, flipTurn,
// checkActionPhaseEnd, DicePoolProvider) live in action_execute_other.go.

func (g *Game) executeSkill(action Action) StepResult {
	pi := action.PlayerIdx
	p := &g.Players[pi]

	// Pay dice (Phase IV: skill cost is in dice, not AP)
	g.PayDice(pi, action.DicePayment)

	// HookActionPrepare：DSL 设置行动类型。AppliedMods 从 action 回填,
	// 让 DSL cost-mod hooks 在自己的 on_action_prepare 里看到自己当初
	// 在枚举阶段是否 apply 了(不过实际消耗查询是在 on_skill_use 里)。
	prepCtx := &EventContext{
		ActionCtx:     ActUseSkill,
		Source:        SrcSkill,
		ActorPlayer:   pi,
		ActorChar:     p.ActiveChar,
		SkillIndex:    action.Index,
		ActionKind:    ActionSkill,
		BattleAction:  true, // 技能默认战斗行动，DSL 可覆盖
		AppliedMods:   action.AppliedMods,
		CurrentHookID: -1,
	}
	g.FireEventHooks(HookActionPrepare, prepCtx)

	g.PushEvent(EventFrame{
		ActionCtx:  ActUseSkill,
		Source:     SrcSkill,
		Player:     pi,
		Char:       p.ActiveChar,
		SkillIndex: action.Index,
	})

	// 技能效果：fire HookSkillUse，由 DSL hook 按 filter 匹配
	// AppliedMods 从 action 回填让消费 hooks 能 was_applied 查询。
	ctx := &EventContext{
		ActionCtx:     ActUseSkill,
		Source:        SrcSkill,
		ActorPlayer:   pi,
		ActorChar:     p.ActiveChar,
		SkillIndex:    action.Index,
		AppliedMods:   action.AppliedMods,
		CurrentHookID: -1,
	}
	g.FireEventHooks(HookSkillUse, ctx)

	g.PopEvent()

	if g.Phase == PhaseGameOver {
		return StepGameOver
	}

	// HookBeforeTurnFlip
	flipCtx := &EventContext{
		ActionCtx:     ActUseSkill,
		Source:        SrcSkill,
		ActorPlayer:   pi,
		ActorChar:     p.ActiveChar,
		SkillIndex:    action.Index,
		BattleAction:  prepCtx.BattleAction,
		AppliedMods:   action.AppliedMods,
		CurrentHookID: -1,
	}
	g.FireEventHooks(HookBeforeTurnFlip, flipCtx)

	if flipCtx.BattleAction {
		g.flipTurn()
	}

	g.checkActionPhaseEnd()
	if g.Phase == PhaseGameOver {
		return StepGameOver
	}
	return StepContinue
}

// executeCard 执行打牌动作
func (g *Game) executeCard(action Action) StepResult {
	pi := action.PlayerIdx
	p := &g.Players[pi]

	if action.Index >= len(p.Hand) {
		return StepContinue
	}
	// Pay dice (Phase IV: card cost is in dice, not AP)
	g.PayDice(pi, action.DicePayment)

	card := p.Hand[action.Index]
	p.Hand = append(p.Hand[:action.Index], p.Hand[action.Index+1:]...)
	p.Discard = append(p.Discard, card)
	if g.Log != nil {
		g.Log.Append(g, "hand_remove", pi, -1, map[string]interface{}{
			"card_ref": card.Ref,
		})
	}

	prepCtx := &EventContext{
		ActionCtx:     ActPlayCard,
		Source:        SrcCard,
		ActorPlayer:   pi,
		ActorChar:     p.ActiveChar,
		CardRef:       card.Ref,
		ActionKind:    ActionCard,
		BattleAction:  false,
		AppliedMods:   action.AppliedMods,
		CurrentHookID: -1,
	}
	g.FireEventHooks(HookActionPrepare, prepCtx)

	// Joint-action style: if the card needs a target, the target was
	// baked into the Action by GetLegalActions. We no longer pause
	// via PendingCardTarget + StepNeedTarget.
	if action.HasTarget {
		return g.resolveCardWithMods(pi, card.Ref, prepCtx.BattleAction, action.TargetPlayer, action.TargetChar, action.AppliedMods)
	}

	// Legacy path: if prepCtx.NeedTarget is set but the action didn't
	// bake in a target (shouldn't happen under the new GetLegalActions,
	// but keep as a safety net), fall through to the pending mechanism.
	if prepCtx.NeedTarget && prepCtx.TargetMode > 0 {
		g.PendingCardTarget = &PendingCard{
			PlayerIdx:    pi,
			CardRef:      card.Ref,
			BattleAction: prepCtx.BattleAction,
			TargetMode:   prepCtx.TargetMode,
		}
		return StepNeedTarget
	}

	return g.resolveCardWithMods(pi, card.Ref, prepCtx.BattleAction, -1, -1, action.AppliedMods)
}

// resolveCard is the legacy entry point (no AppliedMods). Kept for
// PendingCardTarget path.
func (g *Game) resolveCard(pi, cardRef int, battleAction bool, targetPlayer, targetChar int) StepResult {
	return g.resolveCardWithMods(pi, cardRef, battleAction, targetPlayer, targetChar, nil)
}

func (g *Game) resolveCardWithMods(pi, cardRef int, battleAction bool, targetPlayer, targetChar int, appliedMods map[int]bool) StepResult {
	p := &g.Players[pi]

	g.PushEvent(EventFrame{
		ActionCtx: ActPlayCard,
		Source:    SrcCard,
		Player:    pi,
		Char:      p.ActiveChar,
		CardRef:   cardRef,
	})

	ctx := &EventContext{
		ActionCtx:     ActPlayCard,
		Source:        SrcCard,
		ActorPlayer:   pi,
		ActorChar:     p.ActiveChar,
		CardRef:       cardRef,
		TargetPlayer:  targetPlayer,
		TargetChar:    targetChar,
		AppliedMods:   appliedMods,
		CurrentHookID: -1,
	}
	g.FireEventHooks(HookCardPlay, ctx)

	g.PopEvent()

	if g.Phase == PhaseGameOver {
		return StepGameOver
	}

	flipCtx := &EventContext{
		ActionCtx:     ActPlayCard,
		Source:        SrcCard,
		ActorPlayer:   pi,
		ActorChar:     p.ActiveChar,
		CardRef:       cardRef,
		BattleAction:  battleAction,
		AppliedMods:   appliedMods,
		CurrentHookID: -1,
	}
	g.FireEventHooks(HookBeforeTurnFlip, flipCtx)

	if flipCtx.BattleAction {
		g.flipTurn()
	}

	g.checkActionPhaseEnd()
	if g.Phase == PhaseGameOver {
		return StepGameOver
	}
	return StepContinue
}
