package engine

// Counter storage + write pipeline + event stack + event-hook dispatch.
// Counter CRUD (Create/Read/Write) is the lowest-level primitive the DSL
// hooks fire on; the write pipeline wraps it with before/after hook
// dispatch and the event stack tracks the currently-running frame.

// --- Counter ---

func (g *Game) CreateCounter(value, min, max int) int {
	id := len(g.Counters)
	c := Counter{
		BuffIndex: -1,
		Value:     value,
		Init:      value,
		Min:       min,
		Max:       max,
	}
	c.Clamp()
	c.Init = c.Value
	g.Counters = append(g.Counters, c)
	return id
}

func (g *Game) ReadCounter(id int) int {
	if value, ok := g.readIndependentCounter(id); ok {
		return value
	}
	return g.Counters[id].Value
}

func (g *Game) ReadCounterMin(id int) int {
	return g.Counters[id].Min
}

func (g *Game) ReadCounterMax(id int) int {
	return g.Counters[id].Max
}

// --- 写入管道 ---

func (g *Game) FireBeforeWrite(id int, op Op, ctx *EventContext) bool {
	for _, call := range g.scheduleHooks(g.Hooks.GetBeforeWrite(id, op), ctx) {
		g.invokeBuffHook(call, ctx)
		if ctx.Cancelled {
			return false
		}
	}
	return true
}

func (g *Game) ApplyWrite(id int, op Op, value int) {
	if g.writeIndependentCounter(id, op, value) {
		return
	}
	c := &g.Counters[id]
	before := c.Value
	switch op {
	case OpSet:
		c.Value = value
	case OpAdd:
		c.Value += value
	case OpSub:
		c.Value -= value
	}
	c.Clamp()
	g.updateBuffInstance(id, before)
}

func (g *Game) FireAfterWrite(id int, op Op, ctx *EventContext) {
	for _, call := range g.scheduleHooks(g.Hooks.GetAfterWrite(id, op), ctx) {
		g.invokeBuffHook(call, ctx)
	}
}

func (g *Game) WriteCounter(id int, op Op, value int) {
	before := g.ReadCounter(id)
	g.depth++
	defer func() { g.depth-- }()
	g.requireEffectDepth("WriteCounter")
	ctx := &EventContext{
		CounterID: id,
		Op:        op,
		Value:     value,
		Before:    before,
	}
	cur := g.currentEvent()
	if cur.BuffCounterID == id {
		ctx.WriteBuffID = cur.BuffID
	}
	if cur.ActionCtx != ActNone {
		ctx.ActionCtx = cur.ActionCtx
		ctx.Source = cur.Source
		ctx.ActorPlayer = cur.Player
		ctx.ActorChar = cur.Char
	}
	if !g.FireBeforeWrite(id, op, ctx) {
		return
	}
	g.ApplyWrite(id, op, ctx.Value)
	after := g.ReadCounter(id)
	ctx.After = after
	if g.Log != nil && before != after {
		mapping := g.GetCounterChar(id)
		g.Log.Append(g, "counter_write", mapping[0], mapping[1], map[string]interface{}{
			"counter_id": id,
			"op":         int(op),
			"before":     before,
			"after":      after,
			"value":      ctx.Value,
		})
	}
	g.FireAfterWrite(id, op, ctx)
}

// --- 事件栈 ---

func (g *Game) PushEvent(frame EventFrame) {
	g.eventStack = append(g.eventStack, eventLayer{Current: frame})
}

func (g *Game) PopEvent() {
	if len(g.eventStack) > 0 {
		g.eventStack = g.eventStack[:len(g.eventStack)-1]
	}
}

func (g *Game) Depth() int { return g.depth }

func (g *Game) CurrentEvent() EventFrame {
	return g.currentEvent()
}

func (g *Game) currentEvent() EventFrame {
	if len(g.eventStack) == 0 {
		return EventFrame{}
	}
	return g.eventStack[len(g.eventStack)-1].Current
}

// Defer 将效果追加到当前事件帧的延后队列
func (g *Game) Defer(fn func(g *Game)) {
	if len(g.eventStack) == 0 {
		fn(g) // 无事件帧时立即执行
		return
	}
	layer := &g.eventStack[len(g.eventStack)-1]
	layer.Deferred = append(layer.Deferred, deferredEntry{Fn: fn, Frame: layer.Current})
}

// DeferAction 将需要玩家输入的延后动作追加到队列
func (g *Game) DeferAction(action *Action) {
	if len(g.eventStack) == 0 {
		g.requestDeferredInput(action)
		return
	}
	layer := &g.eventStack[len(g.eventStack)-1]
	layer.Deferred = append(layer.Deferred, deferredEntry{
		Action:    action,
		NeedInput: true,
	})
}

// DrainDeferred 执行当前帧的延后队列
func (g *Game) DrainDeferred() {
	if len(g.eventStack) == 0 {
		return
	}
	idx := len(g.eventStack) - 1
	for len(g.eventStack[idx].Deferred) > 0 {
		if g.Phase == PhaseGameOver {
			g.eventStack[idx].Deferred = nil
			return
		}
		// A callback may PushEvent and reallocate eventStack. Never keep a
		// pointer into the stack across that call.
		entry := g.eventStack[idx].Deferred[0]
		g.eventStack[idx].Deferred = g.eventStack[idx].Deferred[1:]
		if entry.NeedInput {
			g.requestDeferredInput(entry.Action)
			if g.PendingAction != nil {
				return
			}
			continue
		}
		if entry.Fn != nil {
			g.runDeferredBuffContext(entry)
		}
	}
}

// --- 事件触发辅助 ---

func (g *Game) FireEventHooks(hookType HookType, ctx *EventContext) {
	for _, call := range g.scheduleHooks(g.Hooks.GetEventHooks(hookType), ctx) {
		if (hookType == HookDamageReduceBuff || hookType == HookShieldAbsorb || hookType == HookDamageImmunity) && ctx.Value <= 0 {
			return
		}
		g.invokeBuffHook(call, ctx)
		if g.Phase == PhaseGameOver {
			return
		}
	}
}
