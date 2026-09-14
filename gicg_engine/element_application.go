package engine

// ApplyElement runs the DSL reaction/attachment rules without a damage pipeline.
// AttachmentOnly lets reaction rules omit collateral damage while retaining
// non-damage consequences such as freezing or forced switches.
func (g *Game) ApplyElement(targetCounter int, elem Element) {
	g.depth++
	defer func() { g.depth-- }()
	g.requireEffectDepth("ApplyElement")
	frame := g.MustCurrentEvent("ApplyElement")
	g.PushEvent(frame)
	defer g.PopEvent()
	p, c := g.findCharByCounter(targetCounter)
	if p < 0 || c < 0 || !g.Players[p].Chars[c].Alive {
		return
	}
	ctx := &EventContext{
		Element: elem, Source: frame.Source, ActorPlayer: frame.Player,
		ActorChar: frame.Char, ActionCtx: frame.ActionCtx, SkillIndex: frame.SkillIndex,
		CardRef: frame.CardRef, TargetPlayer: p, TargetChar: c, AttachmentOnly: true,
	}
	previous := g.PendingReactionKind
	defer func() { g.PendingReactionKind = previous }()
	g.PendingReactionKind = ReactionNone
	g.FireEventHooks(HookReactionDamage, ctx)
	ctx.ReactionKind = g.PendingReactionKind
	g.PendingReactionKind = ReactionNone
	if ctx.ReactionKind != ReactionNone {
		g.FireEventHooks(HookAfterReaction, ctx)
	}
	g.DrainDeferred()
}
