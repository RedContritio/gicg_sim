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
	g.requireEffectDepth("DealDamage")

	// 构建事件帧：opts 可覆盖 source/actor。覆盖作用于已存在的帧之上 —
	// 空栈 + 全量 opts 不是受支持路径(调用方必须先 PushEvent actor 帧)。
	frame := g.MustCurrentEvent("DealDamage")
	if opts.Source != SrcNone {
		frame.Source = opts.Source
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
	if !ctx.Element.IsPiercing() {
		g.FireEventHooks(HookDamageType, ctx)
		if !ctx.Element.IsPiercing() {
			g.FireEventHooks(HookDamageAdd, ctx)
			g.FireEventHooks(HookDamageMul, ctx)
		}
	}
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
		g.FireEventHooks(HookReactionDamage, reactionCtx)
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
		ctx.ReactionElement = reactionCtx.ReactionElement
		// None is a reaction-consumed marker, not the final damage type.
		if ctx.Element == ElemNone {
			ctx.Element = origElement
		}
	}
	// ADR-0019 §B.3: DSL set_reaction_kind 写入 PendingReactionKind,
	// 在 reaction stage 完成后 copy 到 ctx.ReactionKind。
	if g.PendingReactionKind != ReactionNone {
		ctx.ReactionKind = g.PendingReactionKind
		g.PendingReactionKind = ReactionNone
	}
	if ctx.ReactionKind != ReactionNone {
		g.FireEventHooks(HookAfterReaction, ctx)
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
			g.DrainDeferred()
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
	g.DrainDeferred()

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
