package engine

import "fmt"

// executeSwitch / executeEndTurn / executeSelectActive / executeTune
// plus shared helpers (flipTurn, checkActionPhaseEnd, PayDice) and the
// DicePoolProvider interface. Lives beside action_execute.go which hosts
// executeSkill / executeCard.

// executeSwitch 执行切换角色
func (g *Game) executeSwitch(action Action, actCtx ActionContext) StepResult {
	pi := action.PlayerIdx
	p := &g.Players[pi]

	// Pay dice for voluntary switches (Phase IV: 1 any-color dice).
	// Forced switches are free (death-triggered).
	if !action.Forced {
		g.PayDice(pi, action.DicePayment)
	}

	// HookActionPrepare（仅主动切换）
	prepCtx := &EventContext{
		ActionCtx:     actCtx,
		ActorPlayer:   pi,
		ActorChar:     p.ActiveChar,
		ActionKind:    ActionSwitch,
		SwitchChar:    action.Index,
		BattleAction:  !action.Forced, // 主动切换默认战斗行动，强制切换不翻转
		AppliedMods:   action.AppliedMods,
		CurrentHookID: -1,
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
		ActionCtx:     actCtx,
		ActorPlayer:   pi,
		ActorChar:     action.Index,
		AppliedMods:   action.AppliedMods,
		CurrentHookID: -1,
	}
	g.FireEventHooks(HookSwitch, ctx)

	g.PopEvent()

	if g.Phase == PhaseGameOver {
		return StepGameOver
	}

	// 主动切换：走 turn flip 流程
	if !action.Forced {
		flipCtx := &EventContext{
			ActionCtx:     actCtx,
			ActorPlayer:   pi,
			ActorChar:     action.Index,
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
	}

	return StepContinue
}

// flipTurn hands the action to the opponent after a BattleAction, but only
// if the opponent has not yet declared end-of-round. Once a player declares
// end, the other player retains exclusive control until they also declare
// end — this matches the canonical Genshin TCG round structure. Without
// this guard, a DeclaredEnd player keeps getting polled (only able to pick
// EndTurn) and the active player loses one BattleAction worth of tempo per
// flip, which is what produced the random-vs-random P0 ≪ P1 anomaly.
func (g *Game) flipTurn() {
	next := 1 - g.Turn
	if !g.Players[next].DeclaredEnd {
		g.Turn = next
	}
	// Prepare-skill mechanic (ADR-0012): if the player who just got the
	// turn has a pending prepare skill, auto-resolve it (silent invoke)
	// instead of letting them choose an action. Resolving counts as
	// their action and re-flips the turn.
	g.ResolvePreparing()
}

// ResolvePreparing checks Game.Preparing[Turn] and, if a skill is
// queued, silent-invokes it on behalf of the player and re-flips the
// turn. Idempotent against an empty queue. Clears Preparing[Turn]
// before invoking so a recursive call(via the chained flipTurn at end)
// won't re-fire the same skill.
func (g *Game) ResolvePreparing() {
	pi := g.Turn
	skillID := g.Preparing[pi]
	if skillID == 0 {
		return
	}
	g.Preparing[pi] = 0
	activeChar := g.Players[pi].ActiveChar
	g.PushEvent(EventFrame{
		ActionCtx:  ActUseSkill,
		Source:     SrcSkill,
		Player:     pi,
		Char:       activeChar,
		SkillIndex: skillID,
	})
	ctx := &EventContext{
		ActionCtx:      ActUseSkill,
		Source:         SrcSkill,
		ActorPlayer:    pi,
		ActorChar:      activeChar,
		SkillIndex:     skillID,
		Paid:           true,
		SkipSkillHooks: true,
	}
	g.FireEventHooks(HookSkillUse, ctx)
	g.PopEvent()
	// Resolution itself counts as an action; flip the turn again. Will
	// recurse into ResolvePreparing if the *other* side is also prepared
	// (rare but must be safe).
	g.flipTurn()
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

	// 双方都选完了：第一回合固定 P0 先手
	g.Turn = 0
	g.enterRoundPause()
	return StepContinue
}

func (g *Game) checkActionPhaseEnd() {
	if g.Players[0].DeclaredEnd && g.Players[1].DeclaredEnd {
		g.EndPhase()
	}
}

// PayDice debits the dice pool for the given player by the action's
// DicePayment. Called from executeSkill / executeCard / executeSwitch
// before the action's main effect fires, so the dice are gone by the
// time DSL hooks observe the state.
//
// Panics on out-of-range player, a missing DicePoolProvider in
// g.Extra, or a payment value that would drive a counter negative —
// all of those indicate a programmer or ruleset bug, not a runtime
// condition the engine should absorb.
func (g *Game) PayDice(playerIdx int, payment [DiceColorCount]int8) {
	if playerIdx < 0 || playerIdx > 1 {
		panic(fmt.Errorf("PayDice: playerIdx=%d out of range [0,1]", playerIdx))
	}
	rt := g.Extra.(DicePoolProvider)
	for color := 0; color < DiceColorCount; color++ {
		n := int(payment[color])
		if n == 0 {
			continue
		}
		cid := rt.DiceCounterID(playerIdx, color)
		g.Counters[cid].Value -= n
		if g.Counters[cid].Value < 0 {
			panic(fmt.Errorf(
				"PayDice: player=%d color=%d paid %d, pool went below zero",
				playerIdx, color, n))
		}
		// Accumulate into per-player per-color payment history. IS-MCTS
		// uses this as public observation to build a Bayesian dice
		// posterior (Dirichlet prior + paid counts → Dirichlet
		// posterior → sample Multinomial for remaining dice), replacing
		// the uniform-prior approximation in sample_opponent_dice.
		g.DicePaid[playerIdx][color] += n
	}
}

// DicePoolProvider is the interface implemented by interp.Runtime
// so engine code can look up dice counter IDs and cost definitions
// without importing interp (which would create a circular dependency).
type DicePoolProvider interface {
	DiceCounterID(playerIdx, color int) int
	SkillCost(skillID int) (Cost, bool)
	CardCost(cardRef int) (Cost, bool)
}

// executeTune handles Kind=ActionTune: consume 1 hand card and convert
// 1 non-native-element non-omni dice to the active character's element.
// Tune is a "free" action (no dice cost) — it costs a card, not dice.
func (g *Game) executeTune(action Action) StepResult {
	pi := action.PlayerIdx
	handIdx := action.Index
	sourceColor := action.TuneSourceColor
	p := &g.Players[pi]

	// Sanity checks
	if handIdx < 0 || handIdx >= len(p.Hand) {
		return StepContinue
	}
	if sourceColor < 0 || sourceColor >= DiceColorCount {
		return StepContinue
	}
	if p.ActiveChar < 0 || p.ActiveChar >= len(p.Chars) {
		return StepContinue
	}
	targetElem := p.Chars[p.ActiveChar].Element
	targetColor := ElementToDiceColor(targetElem)
	if targetColor < 0 {
		return StepContinue // active char has no dice-color element (ElemNone/Physical)
	}

	rt := g.Extra.(DicePoolProvider)
	sourceCID := rt.DiceCounterID(pi, sourceColor)
	targetCID := rt.DiceCounterID(pi, targetColor)
	if g.Counters[sourceCID].Value <= 0 {
		return StepContinue
	}

	// Do the conversion
	g.Counters[sourceCID].Value--
	g.Counters[targetCID].Value++
	// Track per-color tune activity as public Bayesian evidence for
	// IS-MCTS dice posterior — complements DicePaid (which only covers
	// PayDice, missing tune's explicit color consumption). source_color
	// tells us opponent had ≥1 of that color at tune time;
	// target_color is a known add (kept as future evidence refinement,
	// not used in current posterior).
	g.DiceTunedOut[pi][sourceColor]++
	g.DiceTunedIn[pi][targetColor]++

	// Discard the used card
	card := p.Hand[handIdx]
	p.Discard = append(p.Discard, card)
	p.Hand = append(p.Hand[:handIdx], p.Hand[handIdx+1:]...)

	if g.Log != nil {
		g.Log.Append(g, "tune", pi, -1, map[string]interface{}{
			"card_ref":   card.Ref,
			"from_color": sourceColor,
			"to_color":   targetColor,
		})
	}

	// ADR-0019 §A.4 — 调和 hook (DSL on_tune):卡作元素调和使用时触发,
	// 让卡自身或其它系统对调和事件做反应 (例如桓那兰那 6603 "调和此牌时
	// X" / 5488 换班时间 类卡)。ctx.card_ref 是被调和的卡 ref,
	// ctx.actor_player 是调和方;source/target_color 写入 Source/CardRef
	// 不便扩展,通过 g.Players[pi] 间接读 (DSL 需要时再补 ctx 字段)。
	g.PushEvent(EventFrame{
		ActionCtx: ActPlayCard, // 借用 (调和 = 卡作另类使用),DSL 通过 source 区分
		Source:    SrcCard,
		Player:    pi,
		Char:      p.ActiveChar,
		CardRef:   card.Ref,
	})
	tuneCtx := &EventContext{
		ActionCtx:   ActPlayCard,
		Source:      SrcCard,
		ActorPlayer: pi,
		ActorChar:   p.ActiveChar,
		CardRef:     card.Ref,
	}
	g.FireEventHooks(HookOnTune, tuneCtx)
	g.PopEvent()

	return StepContinue
}
