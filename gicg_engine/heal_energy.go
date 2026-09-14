package engine

// Heal 回复 HP，走治疗管道
func (g *Game) Heal(targetHP int, value int) {
	targetPlayer, targetChar := g.findCharByCounter(targetHP)

	cur := g.MustCurrentEvent("Heal")
	ctx := &EventContext{
		Value:        value,
		Source:       cur.Source,
		ActorPlayer:  cur.Player,
		ActorChar:    cur.Char,
		ActionCtx:    cur.ActionCtx,
		SkillIndex:   cur.SkillIndex,
		CardRef:      cur.CardRef,
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
	g.depth++
	defer func() { g.depth-- }()
	g.requireEffectDepth("GainEnergy")
	targetPlayer, targetChar := g.findCharByCounter(targetEnergy)

	cur := g.MustCurrentEvent("GainEnergy")
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

	before := g.ReadCounter(targetEnergy)
	g.WriteCounter(targetEnergy, OpAdd, ctx.Value)
	ctx.Value = g.ReadCounter(targetEnergy) - before
	if ctx.Value > 0 {
		g.FireEventHooks(HookAfterEnergyGain, ctx)
	}
}

// ConsumeEnergy 走能量消耗管道
func (g *Game) ConsumeEnergy(targetEnergy int, value int) {
	targetPlayer, targetChar := g.findCharByCounter(targetEnergy)

	cur := g.MustCurrentEvent("ConsumeEnergy")
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
