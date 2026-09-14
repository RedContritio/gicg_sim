package engine

// ResolvePreparing silent-invokes the queued skill and hands off the turn.
// Clearing the slot before invocation prevents chained preparation from
// re-firing this skill. Required input uses the same driver as ordinary steps.
func (g *Game) ResolvePreparing() {
	g.runBoundary(boundaryOperation{kind: boundaryPreparing})
}

func (g *Game) resolvePreparing() {
	pi := g.Turn
	skillID := g.Preparing[pi]
	if skillID == 0 {
		return
	}
	g.Preparing[pi] = 0
	activeChar := g.Players[pi].ActiveChar
	g.publicSkill(pi, activeChar, skillID)
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
	g.DrainDeferred()
	g.PopEvent()
	g.flipTurn()
}
