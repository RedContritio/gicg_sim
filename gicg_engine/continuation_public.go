package engine

// This is an observation summary, NOT a replacement execution stack. It is
// populated only at publicly declared action/round boundaries, never from a
// private hook's call stack, branch conditions, RNG or deferred captures.
type publicCause struct {
	Kind, Player, Char, Hook, TargetPlayer, TargetChar, Stage int
}

const (
	CauseSkill = iota + 1
	CauseCard
	CauseRound
	CauseSwitch
)

const ProgramPublicCause = 3 // EntityExecutionFrame, distinct from the waiting frame

func (g *Game) publicSkill(pi, char, skill int) {
	if g.executing == nil {
		return
	}
	hook := -1
	if id, ok := g.CanonicalSkillHooks[[3]int{pi, char, skill}]; ok {
		hook = id
	}
	g.executing.public = publicCause{CauseSkill, pi, char, hook, -1, -1, 0}
}

func (g *Game) publicCard(pi, char, ref, targetPlayer, targetChar int) {
	if g.executing == nil {
		return
	}
	hook := -1
	if id, ok := g.CanonicalCardHooks[ref]; ok {
		hook = id
	}
	g.executing.public = publicCause{CauseCard, pi, char, hook, targetPlayer, targetChar, 0}
}

func (g *Game) publicRound(stage HookType) {
	if g.executing != nil {
		g.executing.public = publicCause{CauseRound, -1, -1, -1, -1, -1, int(stage)}
	}
}

// A second row records what publicly started the interrupted operation. It
// remains incomplete: it describes neither the unexecuted statements nor the
// private control flow. Existing kind vocabulary and tensor widths stay fixed.
func (g *Game) writePublicCauseObs(out []int32, perspective, row int, hooks map[int]int) int {
	if g.resume == nil || g.resume.public.Kind == 0 {
		return row
	}
	if row >= ObsBuffRows {
		panic("public continuation observation capacity exceeded")
	}
	c := g.resume.public
	hook := -1
	if c.Hook >= 0 {
		if index, ok := hooks[c.Hook]; ok {
			hook = index
		}
	}
	values := []int32{1, relativePlayer(c.Player, perspective), int32(c.Char), 0,
		int32(c.Kind), int32(c.Stage), 0, int32(hook), ProgramPublicCause,
		int32(len(g.resume.choices)), 0, 0, EntityExecutionFrame, -1,
		relativePlayer(c.TargetPlayer, perspective), int32(c.TargetChar)}
	copy(out[row*ObsBuffFields:], values)
	return row + 1
}
