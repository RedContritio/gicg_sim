// core/mod.go
package core

// EventType 事件类型
type EventType string

const (
	EventStartPhase     EventType = "start_phase"
	EventEndPhase       EventType = "end_phase"
	EventRoundEnd       EventType = "round_end"
	EventBattleStart    EventType = "battle_start"
	EventSkillUse       EventType = "skill_use"
	EventDamageCalc     EventType = "on_damage_calc"
	EventDamageReceive  EventType = "on_damage_receive"
	EventBeforeSwitch   EventType = "before_switch"
	EventAfterSwitch    EventType = "after_switch"
)

// ModContext Mod 上下文
type ModContext struct {
	Game        *GameState
	Side        *Side
	SourceChar  *Character
	TargetChar  *Character
	DamageInfo  *DamageInfo
	SkillID     string
	Canceled    bool
}

// ModFunc Mod 处理函数
type ModFunc func(ctx *ModContext)

// Mod Mod 定义
type Mod struct {
	ID      string
	Source  string // 来源角色/卡牌 ID
	Event   EventType
	Handler ModFunc
}

// ModManager Mod 管理器
type ModManager struct {
	mods map[EventType][]*Mod
	side *Side
}

// NewModManager 创建 Mod 管理器
func NewModManager(side *Side) *ModManager {
	return &ModManager{
		mods: make(map[EventType][]*Mod),
		side: side,
	}
}

// Attach 附加 Mod
func (mm *ModManager) Attach(mod *Mod) {
	mm.mods[mod.Event] = append(mm.mods[mod.Event], mod)
}

// Trigger 触发事件
func (mm *ModManager) Trigger(event EventType, ctx *ModContext) {
	mods, ok := mm.mods[event]
	if !ok {
		return
	}
	
	for _, mod := range mods {
		if ctx.Canceled {
			break
		}
		mod.Handler(ctx)
	}
}

// GetMods 获取某事件的所有 Mod
func (mm *ModManager) GetMods(event EventType) []*Mod {
	return mm.mods[event]
}

// Clear 清除所有 Mod
func (mm *ModManager) Clear() {
	mm.mods = make(map[EventType][]*Mod)
}

// ClearBySource 清除某来源的所有 Mod
func (mm *ModManager) ClearBySource(source string) {
	for event, mods := range mm.mods {
		var newMods []*Mod
		for _, mod := range mods {
			if mod.Source != source {
				newMods = append(newMods, mod)
			}
		}
		mm.mods[event] = newMods
	}
}
