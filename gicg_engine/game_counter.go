package engine

// Counter storage + write pipeline + event stack + event-hook dispatch.
// Counter CRUD (Create/Read/Write) is the lowest-level primitive the DSL
// hooks fire on; the write pipeline wraps it with before/after hook
// dispatch and the event stack tracks the currently-running frame.

// --- Counter ---

func (g *Game) CreateCounter(value, min, max int) int {
	id := len(g.Counters)
	c := Counter{
		Value: value,
		Init:  value,
		Min:   min,
		Max:   max,
	}
	c.Clamp()
	c.Init = c.Value
	g.Counters = append(g.Counters, c)
	return id
}

func (g *Game) ReadCounter(id int) int {
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
	for _, h := range g.Hooks.GetBeforeWrite(id, op) {
		if !h.Enabled {
			continue
		}
		ctx.CurrentHookID = h.ID
		h.Fn(g, ctx)
		ctx.CurrentHookID = -1
		if ctx.Cancelled {
			return false
		}
	}
	return true
}

func (g *Game) ApplyWrite(id int, op Op, value int) {
	c := &g.Counters[id]
	switch op {
	case OpSet:
		c.Value = value
	case OpAdd:
		c.Value += value
	case OpSub:
		c.Value -= value
	}
	c.Clamp()
}

func (g *Game) FireAfterWrite(id int, op Op, ctx *EventContext) {
	for _, h := range g.Hooks.GetAfterWrite(id, op) {
		if !h.Enabled {
			continue
		}
		ctx.CurrentHookID = h.ID
		h.Fn(g, ctx)
		ctx.CurrentHookID = -1
	}
}

func (g *Game) WriteCounter(id int, op Op, value int) {
	before := g.Counters[id].Value
	g.depth++
	defer func() { g.depth-- }()
	if g.depth > MaxDepth {
		return
	}
	ctx := &EventContext{
		CounterID: id,
		Op:        op,
		Value:     value,
		Before:    before,
	}
	if cur := g.currentEvent(); cur.ActionCtx != ActNone {
		ctx.ActionCtx = cur.ActionCtx
		ctx.Source = cur.Source
		ctx.ActorPlayer = cur.Player
		ctx.ActorChar = cur.Char
	}
	if !g.FireBeforeWrite(id, op, ctx) {
		return
	}
	g.ApplyWrite(id, op, ctx.Value)
	after := g.Counters[id].Value
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
	layer.Deferred = append(layer.Deferred, deferredEntry{Fn: fn})
}

// DeferAction 将需要玩家输入的延后动作追加到队列
func (g *Game) DeferAction(action *Action) {
	if len(g.eventStack) == 0 {
		g.PendingAction = action
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
	layer := &g.eventStack[len(g.eventStack)-1]
	for len(layer.Deferred) > 0 {
		entry := layer.Deferred[0]
		layer.Deferred = layer.Deferred[1:]
		if entry.NeedInput {
			g.PendingAction = entry.Action
			return // 暂停，等待玩家输入
		}
		if entry.Fn != nil {
			entry.Fn(g)
		}
	}
}

// --- 事件触发辅助 ---

func (g *Game) FireEventHooks(hookType HookType, ctx *EventContext) {
	for _, h := range g.Hooks.GetEventHooks(hookType) {
		if !h.Enabled {
			continue
		}
		ctx.CurrentHookID = h.ID
		h.Fn(g, ctx)
		ctx.CurrentHookID = -1
		if g.Phase == PhaseGameOver {
			return
		}
	}
}

// FirePerPlayerHooks 触发 PerPlayer 事件 hook。
// system hook (OwnerPlayer == FilterAny) 对每个玩家各 fire 一次（ctx.ActorPlayer 依次设为 0, 1）。
// character hook (OwnerPlayer >= 0) 只 fire 一次（ctx.ActorPlayer 设为 OwnerPlayer）。
// playerOrder 控制玩家遍历顺序（如先手/后手）。
func (g *Game) FirePerPlayerHooks(hookType HookType, ctx *EventContext, playerOrder []int) {
	for _, h := range g.Hooks.GetEventHooks(hookType) {
		if !h.Enabled {
			continue
		}
		if h.OwnerPlayer == FilterAny {
			// system hook: fire once per player
			for _, pi := range playerOrder {
				ctx.ActorPlayer = pi
				ctx.CurrentHookID = h.ID
				h.Fn(g, ctx)
				ctx.CurrentHookID = -1
				if g.Phase == PhaseGameOver {
					return
				}
			}
		} else {
			ctx.ActorPlayer = h.OwnerPlayer
			ctx.CurrentHookID = h.ID
			h.Fn(g, ctx)
			ctx.CurrentHookID = -1
			if g.Phase == PhaseGameOver {
				return
			}
		}
	}
}
