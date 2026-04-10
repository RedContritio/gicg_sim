package engine

type Action struct {
	Kind      ActionKind
	PlayerIdx int
	Index     int  // 技能索引 / 手牌索引 / 角色索引
	Forced    bool // 强制切换（死亡/超载），不消耗 AP，不翻转行动权
}

// GetLegalActions 纯结构化枚举 + HookActionCheck 过滤。
// 引擎不做任何条件判断（AP、能量、冻结等由 DSL hook 检查）。
func (g *Game) GetLegalActions() []Action {
	if g.Phase == PhaseGameOver {
		return nil
	}

	// 首回合选择出战角色：所有角色可选
	if g.Phase == PhaseSelectActive {
		return g.selectActiveActions(g.Turn)
	}

	if g.Phase != PhaseAction {
		return nil
	}

	if g.PendingAction != nil && g.PendingAction.Kind == ActionSwitch {
		return g.forcedSwitchActions(g.PendingAction.PlayerIdx)
	}

	if g.PendingCardTarget != nil {
		return g.cardTargetActions(g.PendingCardTarget)
	}

	pi := g.Turn
	p := &g.Players[pi]

	// 枚举所有候选
	var candidates []Action

	// 技能候选（ActiveChar 未选择时跳过）
	if p.ActiveChar < 0 || p.ActiveChar >= len(p.Chars) {
		// 异常状态，只返回结束回合
		return []Action{{Kind: ActionEndTurn, PlayerIdx: pi}}
	}
	active := &p.Chars[p.ActiveChar]
	if active.Alive {
		for _, skillID := range active.Skills {
			candidates = append(candidates, Action{
				Kind:      ActionSkill,
				PlayerIdx: pi,
				Index:     skillID,
			})
		}
	}

	// 卡牌候选
	for j := range p.Hand {
		candidates = append(candidates, Action{
			Kind:      ActionCard,
			PlayerIdx: pi,
			Index:     j,
		})
	}

	// 切换候选
	for k, ch := range p.Chars {
		if k == p.ActiveChar || !ch.Alive {
			continue
		}
		candidates = append(candidates, Action{
			Kind:      ActionSwitch,
			PlayerIdx: pi,
			Index:     k,
		})
	}

	// HookActionCheck 过滤
	var actions []Action
	for _, c := range candidates {
		ctx := &EventContext{
			Playable:     true,
			ActionKind:   c.Kind,
			ActorPlayer:  pi,
			ActorChar:    p.ActiveChar,
			SkillIndex:   c.Index,
			CardRef:      FilterAny,
			HandIndex:    c.Index,
			SwitchChar:   c.Index,
			TargetPlayer: FilterAny,
			TargetChar:   FilterAny,
		}
		if c.Kind == ActionCard && c.Index < len(p.Hand) {
			ctx.CardRef = p.Hand[c.Index].Ref
		}
		g.FireEventHooks(HookActionPrepare, ctx)
		// DEBUG: save prepare state
		apCostAfterPrepare := ctx.APCost
		playableAfterPrepare := ctx.Playable
		_ = apCostAfterPrepare
		_ = playableAfterPrepare
		g.FireEventHooks(HookActionCheck, ctx)
		if ctx.Playable {
			actions = append(actions, c)
		}
	}

	// 结束回合始终可用
	actions = append(actions, Action{
		Kind:      ActionEndTurn,
		PlayerIdx: pi,
	})

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

// Step 从合法动作列表中按索引选择动作并执行
func (g *Game) Step(actionIdx int) StepResult {
	if g.Phase == PhaseGameOver {
		return StepGameOver
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

	return g.resolveCard(pc.PlayerIdx, pc.CardRef, pc.BattleAction, chosen.PlayerIdx, chosen.Index)
}

// executeSkill 执行技能动作
func (g *Game) executeSkill(action Action) StepResult {
	pi := action.PlayerIdx
	p := &g.Players[pi]

	// HookActionPrepare：DSL 设置/修改费用和行动类型
	prepCtx := &EventContext{
		ActionCtx:    ActUseSkill,
		Source:       SrcSkill,
		ActorPlayer:  pi,
		ActorChar:    p.ActiveChar,
		SkillIndex:   action.Index,
		ActionKind:   ActionSkill,
		BattleAction: true, // 技能默认战斗行动，DSL 可覆盖
	}
	g.FireEventHooks(HookActionPrepare, prepCtx)

	g.PushEvent(EventFrame{
		ActionCtx: ActUseSkill,
		Source:    SrcSkill,
		Player:    pi,
		Char:      p.ActiveChar,
	})

	// 技能效果：fire HookSkillUse，由 DSL hook 按 filter 匹配
	ctx := &EventContext{
		ActionCtx:   ActUseSkill,
		Source:      SrcSkill,
		ActorPlayer: pi,
		ActorChar:   p.ActiveChar,
		SkillIndex:  action.Index,
	}
	g.FireEventHooks(HookSkillUse, ctx)

	g.PopEvent()

	if g.Phase == PhaseGameOver {
		return StepGameOver
	}

	// HookBeforeTurnFlip
	flipCtx := &EventContext{
		ActionCtx:    ActUseSkill,
		Source:       SrcSkill,
		ActorPlayer:  pi,
		ActorChar:    p.ActiveChar,
		SkillIndex:   action.Index,
		BattleAction: prepCtx.BattleAction,
	}
	g.FireEventHooks(HookBeforeTurnFlip, flipCtx)

	if flipCtx.BattleAction {
		g.Turn = 1 - g.Turn
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
	card := p.Hand[action.Index]
	p.Hand = append(p.Hand[:action.Index], p.Hand[action.Index+1:]...)

	prepCtx := &EventContext{
		ActionCtx:    ActPlayCard,
		Source:       SrcCard,
		ActorPlayer:  pi,
		ActorChar:    p.ActiveChar,
		CardRef:      card.Ref,
		ActionKind:   ActionCard,
		BattleAction: false,
	}
	g.FireEventHooks(HookActionPrepare, prepCtx)

	if prepCtx.NeedTarget && prepCtx.TargetMode > 0 {
		g.PendingCardTarget = &PendingCard{
			PlayerIdx:    pi,
			CardRef:      card.Ref,
			BattleAction: prepCtx.BattleAction,
			TargetMode:   prepCtx.TargetMode,
		}
		return StepNeedTarget
	}

	return g.resolveCard(pi, card.Ref, prepCtx.BattleAction, -1, -1)
}

func (g *Game) resolveCard(pi, cardRef int, battleAction bool, targetPlayer, targetChar int) StepResult {
	p := &g.Players[pi]

	g.PushEvent(EventFrame{
		ActionCtx: ActPlayCard,
		Source:    SrcCard,
		Player:    pi,
		Char:      p.ActiveChar,
	})

	ctx := &EventContext{
		ActionCtx:    ActPlayCard,
		Source:       SrcCard,
		ActorPlayer:  pi,
		ActorChar:    p.ActiveChar,
		CardRef:      cardRef,
		TargetPlayer: targetPlayer,
		TargetChar:   targetChar,
	}
	g.FireEventHooks(HookCardPlay, ctx)

	g.PopEvent()

	if g.Phase == PhaseGameOver {
		return StepGameOver
	}

	flipCtx := &EventContext{
		ActionCtx:    ActPlayCard,
		Source:       SrcCard,
		ActorPlayer:  pi,
		ActorChar:    p.ActiveChar,
		CardRef:      cardRef,
		BattleAction: battleAction,
	}
	g.FireEventHooks(HookBeforeTurnFlip, flipCtx)

	if flipCtx.BattleAction {
		g.Turn = 1 - g.Turn
	}

	g.checkActionPhaseEnd()
	if g.Phase == PhaseGameOver {
		return StepGameOver
	}
	return StepContinue
}

// executeSwitch 执行切换角色
func (g *Game) executeSwitch(action Action, actCtx ActionContext) StepResult {
	pi := action.PlayerIdx
	p := &g.Players[pi]

	// HookActionPrepare（仅主动切换）
	prepCtx := &EventContext{
		ActionCtx:    actCtx,
		ActorPlayer:  pi,
		ActorChar:    p.ActiveChar,
		ActionKind:   ActionSwitch,
		SwitchChar:   action.Index,
		BattleAction: !action.Forced, // 主动切换默认战斗行动，强制切换不翻转
	}
	if !action.Forced {
		g.FireEventHooks(HookActionPrepare, prepCtx)
	}

	g.PushEvent(EventFrame{
		ActionCtx: actCtx,
		Source:    SrcNone,
		Player:    pi,
		Char:      p.ActiveChar,
	})

	p.ActiveChar = action.Index

	ctx := &EventContext{
		ActionCtx:   actCtx,
		ActorPlayer: pi,
		ActorChar:   action.Index,
	}
	g.FireEventHooks(HookSwitch, ctx)

	g.PopEvent()

	if g.Phase == PhaseGameOver {
		return StepGameOver
	}

	// 主动切换：走 turn flip 流程
	if !action.Forced {
		flipCtx := &EventContext{
			ActionCtx:    actCtx,
			ActorPlayer:  pi,
			ActorChar:    action.Index,
			BattleAction: prepCtx.BattleAction,
		}
		g.FireEventHooks(HookBeforeTurnFlip, flipCtx)

		if flipCtx.BattleAction {
			g.Turn = 1 - g.Turn
		}

		g.checkActionPhaseEnd()
		if g.Phase == PhaseGameOver {
			return StepGameOver
		}
	}

	return StepContinue
}

// executeEndTurn 执行结束回合
func (g *Game) executeEndTurn(action Action) StepResult {
	pi := action.PlayerIdx
	p := &g.Players[pi]

	if !p.DeclaredEnd {
		p.DeclaredEnd = true
		if g.FirstEnd == -1 {
			g.FirstEnd = pi
		}
	}

	if g.Players[0].DeclaredEnd && g.Players[1].DeclaredEnd {
		g.EndPhase()
		if g.Phase == PhaseGameOver {
			return StepGameOver
		}
		return StepContinue
	}

	g.Turn = 1 - pi
	return StepContinue
}

// executeSelectActive 处理首回合出战角色选择
func (g *Game) executeSelectActive(action Action) StepResult {
	pi := action.PlayerIdx
	g.Players[pi].ActiveChar = action.Index

	// 轮到下一个玩家选
	nextPlayer := 1 - pi
	if g.Players[nextPlayer].ActiveChar < 0 {
		// 下一个玩家还没选（ActiveChar 初始为 -1 表示未选）
		g.Turn = nextPlayer
		return StepContinue
	}

	// 双方都选完了，开始第一回合
	g.NewRound()
	return StepContinue
}

func (g *Game) checkActionPhaseEnd() {
	if g.Players[0].DeclaredEnd && g.Players[1].DeclaredEnd {
		g.EndPhase()
	}
}
