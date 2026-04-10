package engine

// NewRound 开始新回合。
// 引擎只推进阶段和触发 hook，所有规则由 system/ DSL 实现。
func (g *Game) NewRound() {
	g.Phase = PhaseRoundStart
	g.Round++

	order := []int{0, 1}
	ctx := &EventContext{ActionCtx: ActNone}
	g.FirePerPlayerHooks(HookRoundStart, ctx, order)

	g.Phase = PhaseAction
	g.FirstEnd = -1
	g.Players[0].DeclaredEnd = false
	g.Players[1].DeclaredEnd = false
}

// EndPhase 执行结束阶段（严格顺序触发 hook）。
func (g *Game) EndPhase() {
	g.Phase = PhaseRoundEnd

	firstPlayer := g.FirstEnd
	if firstPlayer < 0 {
		firstPlayer = 0
	}
	order := []int{firstPlayer, 1 - firstPlayer}

	ctx := &EventContext{ActionCtx: ActNone}

	// ① 状态结算（先手方 → 后手方）
	g.FirePerPlayerHooks(HookRoundEnd, ctx, order)
	if g.Phase == PhaseGameOver {
		return
	}

	// ② 召唤物结算
	g.FirePerPlayerHooks(HookRoundEndPostSummon, ctx, order)
	if g.Phase == PhaseGameOver {
		return
	}

	// ③ 持续时间衰减
	g.FirePerPlayerHooks(HookRoundEndDecay, ctx, order)
	if g.Phase == PhaseGameOver {
		return
	}

	// ④ 最终结算（draw.lua 抽牌、timeout.lua 判负）
	g.FirePerPlayerHooks(HookRoundEndFinal, ctx, order)
	if g.Phase == PhaseGameOver {
		return
	}

	g.NewRound()
}

// GetReward 返回游戏结束后的奖励
func (g *Game) GetReward(player int) float32 {
	if g.Winner == 2 {
		return 0
	}
	if g.Winner == player {
		return 1
	}
	return -1
}

// GetWinner 返回胜者（-1=进行中, 0=P0胜, 1=P1胜, 2=平局）
func (g *Game) GetWinner() int {
	return g.Winner
}
