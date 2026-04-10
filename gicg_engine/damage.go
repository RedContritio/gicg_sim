package engine

type DamageOpts struct {
	Penetrate   bool
	Source      Source // 覆盖事件栈 Source（SrcNone = 不覆盖）
	ActorPlayer int   // 覆盖事件栈 Player（-1 = 不覆盖）
	ActorChar   int   // 覆盖事件栈 Char（-1 = 不覆盖）
}

// DealDamage 执行完整伤害管道。
// targetHP 是目标 HP 的 counter ID（由 DSL 解析目标后传入）。
func (g *Game) DealDamage(targetHP int, elem Element, value int, opts DamageOpts) {
	g.depth++
	defer func() { g.depth-- }()
	if g.depth > MaxDepth {
		return
	}

	// 构建事件帧：opts 可覆盖 source/actor
	frame := g.currentEvent()
	frame.Source = opts.Source
	if frame.Source == SrcNone {
		if cur := g.currentEvent(); cur.Source != SrcNone {
			frame.Source = cur.Source
		}
	}
	if opts.ActorPlayer >= 0 {
		frame.Player = opts.ActorPlayer
	}
	if opts.ActorChar >= 0 {
		frame.Char = opts.ActorChar
	}
	g.PushEvent(frame)
	defer g.PopEvent()

	// 找到目标角色
	targetPlayer, targetChar := g.findCharByCounter(targetHP)

	ctx := &EventContext{
		Value:        value,
		Element:      elem,
		Penetrate:    opts.Penetrate,
		Source:       frame.Source,
		ActorPlayer:  frame.Player,
		ActorChar:    frame.Char,
		ActionCtx:    frame.ActionCtx,
		TargetPlayer: targetPlayer,
		TargetChar:   targetChar,
	}

	// ① 增伤（附魔、加伤）
	g.FireEventHooks(HookDamageBoost, ctx)
	if ctx.Cancelled || g.Phase == PhaseGameOver {
		return
	}

	// ② 反应
	if !ctx.SkipReaction {
		reactionCtx := &EventContext{
			Value:        ctx.Value,
			Element:      ctx.Element,
			ActionCtx:    ctx.ActionCtx,
			Source:       ctx.Source,
			ActorPlayer:  ctx.ActorPlayer,
			ActorChar:    ctx.ActorChar,
			TargetPlayer: targetPlayer,
			TargetChar:   targetChar,
		}
		for _, h := range g.Hooks.GetEventHooks(HookReactionDamage) {
			if !h.Enabled {
				continue
			}
			h.Fn(g, reactionCtx)
		}
		ctx.Value = reactionCtx.Value
		ctx.Element = reactionCtx.Element
	}

	// ③ 减伤（护盾吸收，仅非穿透）
	if !ctx.Penetrate && ctx.Value > 0 {
		g.FireEventHooks(HookDamageReduce, ctx)
		if ctx.Cancelled || ctx.Value <= 0 {
			g.DrainDeferred()
			g.fireAfterDamage(ctx)
			return
		}
	}

	// ④ HP 扣减
	if ctx.Value > 0 {
		g.WriteCounter(targetHP, OpSub, ctx.Value)
		ctx.Hit = true
	}

	g.DrainDeferred()

	// ⑤ AfterDamage
	g.fireAfterDamage(ctx)
}

func (g *Game) fireAfterDamage(ctx *EventContext) {
	for _, h := range g.Hooks.GetEventHooks(HookAfterDamage) {
		if !h.Enabled {
			continue
		}
		h.Fn(g, ctx)
	}
}

// Heal 回复 HP，走治疗管道
func (g *Game) Heal(targetHP int, value int) {
	targetPlayer, targetChar := g.findCharByCounter(targetHP)

	cur := g.currentEvent()
	ctx := &EventContext{
		Value:        value,
		Source:       cur.Source,
		ActorPlayer:  cur.Player,
		ActorChar:    cur.Char,
		ActionCtx:    cur.ActionCtx,
		TargetPlayer: targetPlayer,
		TargetChar:   targetChar,
	}

	g.FireEventHooks(HookBeforeHeal, ctx)
	if ctx.Value <= 0 {
		return
	}

	g.WriteCounter(targetHP, OpAdd, ctx.Value)
	ctx.Hit = true

	g.FireEventHooks(HookAfterHeal, ctx)
}

// GainEnergy 走能量获得管道
func (g *Game) GainEnergy(targetEnergy int, value int) {
	targetPlayer, targetChar := g.findCharByCounter(targetEnergy)

	cur := g.currentEvent()
	ctx := &EventContext{
		Value:        value,
		Source:       cur.Source,
		ActorPlayer:  cur.Player,
		ActorChar:    cur.Char,
		ActionCtx:    cur.ActionCtx,
		TargetPlayer: targetPlayer,
		TargetChar:   targetChar,
	}

	g.FireEventHooks(HookBeforeEnergyGain, ctx)
	if ctx.Value <= 0 {
		return
	}

	g.WriteCounter(targetEnergy, OpAdd, ctx.Value)
	g.FireEventHooks(HookAfterEnergyGain, ctx)
}

// ConsumeEnergy 走能量消耗管道
func (g *Game) ConsumeEnergy(targetEnergy int, value int) {
	targetPlayer, targetChar := g.findCharByCounter(targetEnergy)

	cur := g.currentEvent()
	ctx := &EventContext{
		Value:        value,
		Source:       cur.Source,
		ActorPlayer:  cur.Player,
		ActorChar:    cur.Char,
		ActionCtx:    cur.ActionCtx,
		TargetPlayer: targetPlayer,
		TargetChar:   targetChar,
	}

	g.FireEventHooks(HookBeforeEnergyConsume, ctx)
	if ctx.Value <= 0 {
		return
	}

	g.WriteCounter(targetEnergy, OpSub, ctx.Value)
	g.FireEventHooks(HookAfterEnergyConsume, ctx)
}

// findCharByCounter 根据 counter ID 查找所属角色
func (g *Game) findCharByCounter(counterID int) (playerIdx, charIdx int) {
	if g.counterCharMap != nil {
		if pair, ok := g.counterCharMap[counterID]; ok {
			return pair[0], pair[1]
		}
	}
	return -1, -1
}
