package engine

import "math/rand"

// enterRoundPause 进入回合间暂停状态。在 PhaseRoundStart 中，counter 值即为
// 即将开始的回合的"初始状态"（hooks 未触发，AP 未重置，卡未摸）。
// 此处捕获 RoundStartSnap，下次 Step/GetLegalActions 会自动调用 NewRound 推进。
func (g *Game) enterRoundPause() {
	g.Phase = PhaseRoundStart
	if g.Log != nil {
		snap := g.Snapshot()
		// Resolve who will go first next round (same logic as NewRound).
		firstPlayer := g.Turn
		if g.FirstEnd >= 0 {
			firstPlayer = g.FirstEnd
		}
		snap.FirstPlayer = firstPlayer
		g.Log.RoundStartSnaps = append(g.Log.RoundStartSnaps, snap)
	}
}

// NewRound 开始新回合：推进回合计数，触发 round_start hooks，进入行动阶段。
// 调用前 g.Phase 应为 PhaseRoundStart。
func (g *Game) NewRound() {
	g.Round++

	// Re-seed Rng deterministically from (BaseSeed, Round) before any
	// round_start hook observes it. Dice rolls therefore depend only on
	// (BaseSeed, Round), not on how much play advanced Rng in earlier
	// rounds — so replaying from a mid-game snapshot produces the same
	// rolls as the original recording.
	if g.BaseSeed != 0 || g.Round > 0 {
		g.Rng = rand.New(rand.NewSource(g.BaseSeed + int64(g.Round)*999331))
	}

	if g.Log != nil {
		g.Log.Append(g, "round_start", -1, -1, nil)
	}

	// 先手方：若上回合有人先宣告结束，由其先手；否则按 g.Turn 现有值（第 1 回合为 P0）
	firstPlayer := g.Turn
	if g.FirstEnd >= 0 {
		firstPlayer = g.FirstEnd
	}
	g.Turn = firstPlayer
	order := []int{firstPlayer, 1 - firstPlayer}
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
	if g.Log != nil {
		g.Log.Append(g, "round_end", -1, -1, nil)
	}

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

	// MaxRounds hard cap (curriculum Stage 0+). Applied AFTER timeout.lua's
	// own alive-count tiebreak at round 10 has had a chance to fire; only
	// force a draw here if no DSL hook set a winner and the configured
	// ceiling has been reached. MaxRounds = 0 disables this path entirely,
	// preserving pre-curriculum behavior.
	if g.MaxRounds > 0 && g.Round >= g.MaxRounds {
		g.Phase = PhaseGameOver
		g.Winner = 2
		if g.Log != nil {
			g.Log.Append(g, "max_rounds_draw", -1, -1, nil)
		}
		return
	}

	// 进入回合间暂停（PhaseRoundStart）。捕获快照作为下回合的初始状态。
	// 下一次 Step() 调用会自动通过 NewRound() 推进到下回合。
	g.enterRoundPause()
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
