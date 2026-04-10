package engine

// Filter 特殊值
const (
	FilterAny    = -1 // 匹配任意
	FilterSelf   = -2 // 匹配 hook 所属角色（角色级）
	FilterActive = -3 // 匹配 hook 所属玩家的当前出战角色（槽位级）
)

type HookFn func(g *Game, ctx *EventContext)

type Hook struct {
	ID          int
	Type        HookType
	CounterID   int
	Op          Op
	Fn          HookFn
	OwnerPlayer int
	OwnerChar   int
	Enabled     bool
	Priority    int
}

type writeKey struct {
	CounterID int
	Op        Op
}

type HookRegistry struct {
	hooks  []*Hook
	nextID int

	beforeWrite map[writeKey][]*Hook
	afterWrite  map[writeKey][]*Hook
	eventHooks  map[HookType][]*Hook
}

func NewHookRegistry() *HookRegistry {
	return &HookRegistry{
		beforeWrite: make(map[writeKey][]*Hook),
		afterWrite:  make(map[writeKey][]*Hook),
		eventHooks:  make(map[HookType][]*Hook),
	}
}

func (r *HookRegistry) Register(h Hook) int {
	h.ID = r.nextID
	r.nextID++
	h.Enabled = true
	ptr := &h
	r.hooks = append(r.hooks, ptr)

	insert := func(list []*Hook, h *Hook) []*Hook {
		i := len(list)
		for i > 0 && list[i-1].Priority < h.Priority {
			i--
		}
		list = append(list, nil)
		copy(list[i+1:], list[i:])
		list[i] = h
		return list
	}

	switch h.Type {
	case HookBeforeWrite:
		k := writeKey{h.CounterID, h.Op}
		r.beforeWrite[k] = insert(r.beforeWrite[k], ptr)
	case HookAfterWrite:
		k := writeKey{h.CounterID, h.Op}
		r.afterWrite[k] = insert(r.afterWrite[k], ptr)
	default:
		r.eventHooks[h.Type] = insert(r.eventHooks[h.Type], ptr)
	}
	return h.ID
}

func (r *HookRegistry) Remove(id int) {
	if id < 0 || id >= len(r.hooks) {
		return
	}
	h := r.hooks[id]
	if h == nil {
		return
	}
	h.Enabled = false

	removeFrom := func(list []*Hook) []*Hook {
		out := list[:0]
		for _, item := range list {
			if item.ID != id {
				out = append(out, item)
			}
		}
		return out
	}

	switch h.Type {
	case HookBeforeWrite:
		k := writeKey{h.CounterID, h.Op}
		r.beforeWrite[k] = removeFrom(r.beforeWrite[k])
	case HookAfterWrite:
		k := writeKey{h.CounterID, h.Op}
		r.afterWrite[k] = removeFrom(r.afterWrite[k])
	default:
		r.eventHooks[h.Type] = removeFrom(r.eventHooks[h.Type])
	}
}

func (r *HookRegistry) GetBeforeWrite(counterID int, op Op) []*Hook {
	return r.beforeWrite[writeKey{counterID, op}]
}

func (r *HookRegistry) GetAfterWrite(counterID int, op Op) []*Hook {
	return r.afterWrite[writeKey{counterID, op}]
}

func (r *HookRegistry) GetEventHooks(t HookType) []*Hook {
	return r.eventHooks[t]
}
