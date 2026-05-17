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
	Tokens      []TokenPair // DSL token sequence of the hook body
	// Source is a short tag identifying which DSL file registered this
	// hook (e.g. "铁剑", "赤蝶_蝶火", "round"). Used by the visualizer to
	// disambiguate the dozens of on_card_play / on_damage_boost hooks
	// registered by different files. Empty if not tracked.
	Source string
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

func (r *HookRegistry) AllHooks() []*Hook {
	return r.hooks
}

// HookTypeName returns a short string identifier for a HookType, suitable
// for debug logs and visualizer labels. Unknown types fall back to a
// numeric placeholder so we never crash on new enum values.
func HookTypeName(t HookType) string {
	switch t {
	case HookBeforeWrite:
		return "before_write"
	case HookAfterWrite:
		return "after_write"
	case HookReactionDamage:
		return "on_reaction_damage"
	case HookAfterDamage:
		return "on_after_damage"
	case HookDamageType:
		return "on_damage_type"
	case HookDamageAdd:
		return "on_damage_add"
	case HookDamageMul:
		return "on_damage_mul"
	case HookDamageReduceBuff:
		return "on_damage_reduce_buff"
	case HookShieldAbsorb:
		return "on_shield_absorb"
	case HookDamageImmunity:
		return "on_damage_immunity"
	case HookBeforeHeal:
		return "on_before_heal"
	case HookAfterHeal:
		return "on_after_heal"
	case HookBeforeEnergyGain:
		return "on_before_energy_gain"
	case HookAfterEnergyGain:
		return "on_after_energy_gain"
	case HookBeforeEnergyConsume:
		return "on_before_energy_consume"
	case HookAfterEnergyConsume:
		return "on_after_energy_consume"
	case HookActionCheck:
		return "on_action_check"
	case HookActionPrepare:
		return "on_action_prepare"
	case HookSkillUse:
		return "on_skill_use"
	case HookCardPlay:
		return "on_card_play"
	case HookSwitch:
		return "on_switch"
	case HookBeforeTurnFlip:
		return "on_before_turn_flip"
	case HookOnTune:
		return "on_tune"
	case HookRoundStart:
		return "on_round_start"
	case HookRoundEnd:
		return "on_round_end"
	case HookRoundEndPostSummon:
		return "on_round_end_post_summon"
	case HookRoundEndDecay:
		return "on_round_end_decay"
	case HookRoundEndFinal:
		return "on_round_end_final"
	case HookDeath:
		return "on_death"
	case HookRevive:
		return "on_revive"
	case HookSupportRemove:
		return "on_support_remove"
	case HookAction:
		return "on_action"
	}
	return "?"
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
