package engine

type DamageOpts struct {
	Source      Source // 覆盖事件栈 Source（SrcNone = 不覆盖）
	ActorPlayer int    // 覆盖事件栈 Player（-1 = 不覆盖）
	ActorChar   int    // 覆盖事件栈 Char（-1 = 不覆盖）
}

// DealDamage 执行完整伤害管道。
// targetHP 是目标 HP 的 counter ID（由 DSL 解析目标后传入）。
func (g *Game) DealDamage(targetHP int, elem Element, value int, opts DamageOpts) {
	g.depth++
	defer func() { g.depth-- }()
	if g.depth > MaxDepth {
		if g.Log != nil {
			g.Log.Append(g, "depth_exceeded", -1, -1, map[string]interface{}{"depth": g.depth})
		}
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

	// ADR-0019 §B.2: per-DealDamage call DamageModifierLog 栈;嵌套 damage
	// call 各自独立 log,defer pop。
	g.pushDamageLog()
	defer g.popDamageLog()

	// 找到目标角色
	targetPlayer, targetChar := g.findCharByCounter(targetHP)

	ctx := &EventContext{
		Value:        value,
		Element:      elem,
		Source:       frame.Source,
		ActorPlayer:  frame.Player,
		ActorChar:    frame.Char,
		ActionCtx:    frame.ActionCtx,
		SkillIndex:   frame.SkillIndex,
		CardRef:      frame.CardRef,
		TargetPlayer: targetPlayer,
		TargetChar:   targetChar,
		ReactionKind: ReactionNone, // ADR-0019 §B.3: DSL set_reaction_kind 在反应分支写入
	}

	// ① 增伤 (strict §B.5: Type → Add → Mul)
	//   Type:元素修改 (物理→火附魔)
	//   Add:加法 (班尼特 +2)
	//   Mul:乘法 (GI TCG 无,future-proof)
	// ADR-0019 §B.2 record stage modifier 合并整 boost stage
	boostBeforeVal, boostBeforeElem := ctx.Value, ctx.Element
	g.FireEventHooks(HookDamageType, ctx)
	g.FireEventHooks(HookDamageAdd, ctx)
	g.FireEventHooks(HookDamageMul, ctx)
	g.recordStageModifier(ModBoost, boostBeforeVal, boostBeforeElem, ctx)
	if ctx.Cancelled || g.Phase == PhaseGameOver {
		return
	}

	// ② 反应 — Piercing 跳过(ADR-0019 §B.1);record stage modifier(§B.2)
	// reset PendingReactionKind 在 stage 入口(防止跨 DealDamage call 残留)
	g.PendingReactionKind = ReactionNone
	reactionBeforeVal, reactionBeforeElem := ctx.Value, ctx.Element
	if !ctx.SkipReaction && !ctx.Element.IsPiercing() {
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
		origElement := reactionCtx.Element
		for _, h := range g.Hooks.GetEventHooks(HookReactionDamage) {
			if !h.Enabled {
				continue
			}
			h.Fn(g, reactionCtx)
		}
		// Reaction detection: reaction hooks consume the triggering
		// element and set it to None (0) — so a non-None → None
		// transition is the canonical "a reaction fired" signal.
		if origElement != 0 && reactionCtx.Element == 0 {
			if ctx.ActorPlayer >= 0 && ctx.ActorPlayer < 2 {
				g.RewardAccum[ctx.ActorPlayer].ReactionsTriggered++
			}
			if targetPlayer >= 0 && targetPlayer < 2 {
				g.RewardAccum[targetPlayer].ReactionsReceived++
			}
		}
		ctx.Value = reactionCtx.Value
		ctx.Element = reactionCtx.Element
	}
	// ADR-0019 §B.3: DSL set_reaction_kind 写入 PendingReactionKind,
	// 在 reaction stage 完成后 copy 到 ctx.ReactionKind。
	if g.PendingReactionKind != ReactionNone {
		ctx.ReactionKind = g.PendingReactionKind
		g.PendingReactionKind = ReactionNone
	}
	// ADR-0019 §B.2 record reaction stage modifier(无论是否真触发反应,
	// stage 的 fire 事实本身要 record;skip 时 ValueBefore == ValueAfter)
	g.recordStageModifier(ModReaction, reactionBeforeVal, reactionBeforeElem, ctx)

	// ③ 减伤(strict §B.5: ReduceBuff → ShieldAbsorb → Immunity);仅非穿透(ADR-0019 §B.1)
	preShieldValue := ctx.Value
	reduceBeforeElem := ctx.Element
	if !ctx.Element.IsPiercing() && ctx.Value > 0 {
		g.FireEventHooks(HookDamageReduceBuff, ctx) // 减伤 buff (物理半伤等)
		g.FireEventHooks(HookShieldAbsorb, ctx)     // 护盾消耗
		g.FireEventHooks(HookDamageImmunity, ctx)   // 免疫 (kill all)
		if ctx.Cancelled || ctx.Value <= 0 {
			// Fully absorbed by shields — credit the whole pre-shield
			// value to both sides' accumulators before exiting.
			absorbed := preShieldValue
			if targetPlayer >= 0 && targetPlayer < 2 {
				g.RewardAccum[targetPlayer].ShieldAbsorbed += absorbed
			}
			if ctx.ActorPlayer >= 0 && ctx.ActorPlayer < 2 {
				g.RewardAccum[ctx.ActorPlayer].DamageBlocked += absorbed
			}
			// ADR-0019 §B.2 record reduce stage modifier(全吸收路径 early-return)
			g.recordStageModifier(ModReduce, preShieldValue, reduceBeforeElem, ctx)
			ctx.Absorbed = absorbed // ADR-0019 §B.5: 全吸收路径 absorbed = preShieldValue
			g.DrainDeferred()
			g.fireAfterDamage(ctx)
			return
		}
	}
	// ADR-0019 §B.2 record reduce stage modifier(正常路径)
	g.recordStageModifier(ModReduce, preShieldValue, reduceBeforeElem, ctx)
	shieldAbsorbed := preShieldValue - ctx.Value
	ctx.Absorbed = shieldAbsorbed // ADR-0019 §B.5: on_after_damage 读 ctx.absorbed
	if shieldAbsorbed > 0 {
		if targetPlayer >= 0 && targetPlayer < 2 {
			g.RewardAccum[targetPlayer].ShieldAbsorbed += shieldAbsorbed
		}
		if ctx.ActorPlayer >= 0 && ctx.ActorPlayer < 2 {
			g.RewardAccum[ctx.ActorPlayer].DamageBlocked += shieldAbsorbed
		}
	}

	// ④ HP 扣减
	if ctx.Value > 0 {
		// Log damage BEFORE the HP write — the write may trigger death,
		// and we want "造成伤害" → "死亡" ordering in the replay.
		if g.Log != nil {
			g.Log.Append(g, "damage", ctx.ActorPlayer, ctx.ActorChar, map[string]interface{}{
				"src_player":  ctx.ActorPlayer,
				"src_char":    ctx.ActorChar,
				"tgt_player":  targetPlayer,
				"tgt_char":    targetChar,
				"element":     int(ctx.Element),
				"raw_value":   preShieldValue,
				"final_value": ctx.Value,
				"absorbed":    shieldAbsorbed,
				// ADR-0019 §B.1: penetrate 派生自 element=Piercing,不再单独 log
			})
		}
		g.WriteCounter(targetHP, OpSub, ctx.Value)
		ctx.Hit = true
		if ctx.ActorPlayer >= 0 && ctx.ActorPlayer < 2 {
			g.RewardAccum[ctx.ActorPlayer].DamageDealt += ctx.Value
		}
		if targetPlayer >= 0 && targetPlayer < 2 {
			g.RewardAccum[targetPlayer].DamageReceived += ctx.Value
		}
	}

	g.DrainDeferred()

	// ⑤ AfterDamage
	g.fireAfterDamage(ctx)

	// ADR-0019 §B.3: emit RecentDamageEvent 到 ring (DSL hook chain 全完后).
	// Modifier list 深拷贝,避免后续 damage call 污染 ring 中的 snapshot。
	var modCopy []Modifier
	if log := g.CurrentDamageLog(); log != nil && len(log.Modifiers) > 0 {
		modCopy = make([]Modifier, len(log.Modifiers))
		copy(modCopy, log.Modifiers)
	}
	g.PushRecentDamageEvent(RecentDamageEvent{
		ActorPlayer:  ctx.ActorPlayer,
		ActorChar:    ctx.ActorChar,
		TargetPlayer: targetPlayer,
		TargetChar:   targetChar,
		Element:      ctx.Element,
		RawValue:     preShieldValue,
		FinalValue:   ctx.Value,
		Absorbed:     shieldAbsorbed,
		IsPiercing:   ctx.Element.IsPiercing(),
		IsHit:        ctx.Hit,
		ReactionKind: ctx.ReactionKind,
		Modifiers:    modCopy,
	})
}

func (g *Game) fireAfterDamage(ctx *EventContext) {
	// ADR-0019 §B.2 record after-damage stage modifier
	beforeVal, beforeElem := ctx.Value, ctx.Element
	for _, h := range g.Hooks.GetEventHooks(HookAfterDamage) {
		if !h.Enabled {
			continue
		}
		h.Fn(g, ctx)
	}
	g.recordStageModifier(ModAfterDamage, beforeVal, beforeElem, ctx)
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

	// Credit heal to both sides: the healed player sees HealDone,
	// the opponent sees EnemyHealDone. Symmetric bookkeeping lets a
	// consumer that only reads its own slot still know how much the
	// opponent healed.
	if targetPlayer >= 0 && targetPlayer < 2 {
		g.RewardAccum[targetPlayer].HealDone += ctx.Value
		enemy := 1 - targetPlayer
		g.RewardAccum[enemy].EnemyHealDone += ctx.Value
	}

	// Log heal
	if g.Log != nil {
		g.Log.Append(g, "heal", targetPlayer, targetChar, map[string]interface{}{
			"tgt_player": targetPlayer,
			"tgt_char":   targetChar,
			"value":      ctx.Value,
		})
	}

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
