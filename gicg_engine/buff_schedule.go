package engine

import "sort"

// Every call captures lifecycle identity at event entry; no hook can substitute
// a newly created instance for the instance whose turn was scheduled.
type buffHookCall struct {
	hook     *Hook
	instance uint64
	rank     int
}

func (g *Game) scheduleHooks(hooks []*Hook, ctx *EventContext) []buffHookCall {
	calls := make([]buffHookCall, 0, len(hooks))
	for _, h := range hooks {
		if h.OrderCounter == nil {
			calls = append(calls, buffHookCall{hook: h, rank: -1})
			continue
		}
		id := h.OrderCounter(ctx)
		for rank, b := range g.Buffs {
			if b.Independent && b.Value <= 0 {
				continue
			}
			if g.BuffDefinitions[b.Definition].CounterID == id {
				calls = append(calls, buffHookCall{h, b.ID, rank})
			}
		}
	}
	sort.SliceStable(calls, func(i, j int) bool {
		if calls[i].hook.Priority != calls[j].hook.Priority {
			return calls[i].hook.Priority > calls[j].hook.Priority
		}
		return calls[i].rank < calls[j].rank
	})
	return calls
}

func (g *Game) invokeBuffHook(call buffHookCall, ctx *EventContext) {
	if !call.hook.Enabled || (call.instance != 0 && g.buffByID(call.instance) == nil) {
		return
	}
	oldHook, oldBuff := ctx.CurrentHookID, ctx.BuffID
	ctx.CurrentHookID, ctx.BuffID = call.hook.ID, call.instance
	index := len(g.eventStack) - 1
	var oldFrame EventFrame
	if index >= 0 && call.instance != 0 {
		oldFrame = g.eventStack[index].Current
		g.eventStack[index].Current.BuffID = call.instance
		g.eventStack[index].Current.BuffCounterID = g.BuffDefinitions[g.buffByID(call.instance).Definition].CounterID
	}
	defer func() {
		if index >= 0 && call.instance != 0 {
			g.eventStack[index].Current = oldFrame
		}
		ctx.CurrentHookID, ctx.BuffID = oldHook, oldBuff
	}()
	call.hook.Fn(g, ctx)
}

// Positive keys remain legacy hook IDs. Negative keys identify one application
// by (lifecycle, hook); fixed 32-bit components do not depend on obs capacity.
func (ctx *EventContext) ApplicationKey(hookID int) int {
	if ctx.BuffID == 0 {
		return hookID
	}
	if ctx.BuffID > 0x7ffffffe || hookID < 0 || uint64(hookID) > 0xffffffff {
		panic("modifier application identity overflow")
	}
	return -int((ctx.BuffID<<32)|uint64(hookID)) - 1
}

func (ctx *EventContext) MarkApplied() {
	if ctx.CurrentHookID < 0 {
		return
	}
	if ctx.AppliedMods == nil {
		ctx.AppliedMods = map[int]bool{}
	}
	ctx.AppliedMods[ctx.CurrentHookID] = true // compatibility with fixed legacy consumers
	ctx.AppliedMods[ctx.ApplicationKey(ctx.CurrentHookID)] = true
}

func (g *Game) runDeferredBuffContext(entry deferredEntry) {
	index := len(g.eventStack) - 1
	old := g.eventStack[index].Current
	g.eventStack[index].Current.BuffID = entry.Frame.BuffID
	g.eventStack[index].Current.BuffCounterID = entry.Frame.BuffCounterID
	defer func() { g.eventStack[index].Current = old }()
	entry.Fn(g)
}
