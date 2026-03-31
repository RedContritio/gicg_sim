# GICG 引擎架构设计 v2

## 核心设计理念

**ECS (Entity-Component-System) + 事件驱动**

不是"角色有技能"，而是"世界有实体，系统处理逻辑"。

```
┌─────────────────────────────────────────────────────────────────┐
│                        游戏世界 (World)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  实体1 (e1)  │  │  实体2 (e2)  │  │  实体3 (e3=召唤物奥兹)   │ │
│  │  - HP: 10   │  │  - HP: 8    │  │  - Owner: e1            │ │
│  │  - Energy:3 │  │  - 元素: 火  │  │  - Uses: 2              │ │
│  │  - 附着: 水  │  │  - 状态: []  │  │  - 触发: 结束阶段         │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  全局状态                                                  │  │
│  │  - 当前回合: 3                                            │  │
│  │  - 当前阶段: EndPhase                                     │  │
│  │  - 当前玩家: 0                                            │  │
│  │  - 骰子状态: [...]                                        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Event Queue
┌─────────────────────────────────────────────────────────────────┐
│                      系统层 (Systems)                            │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐ │
│  │ SkillSystem  │ DamageSystem │SummonSystem  │ TokenSystem  │ │
│  │ 技能执行     │ 伤害计算     │ 召唤物管理   │ 状态层数管理  │ │
│  └──────────────┴──────────────┴──────────────┴──────────────┘ │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐ │
│  │ PhaseSystem  │ElementSystem │ LuaRuntime   │ AI/ValidSys  │ │
│  │ 阶段管理     │ 元素反应     │ 脚本执行     │ 动作验证     │ │
│  └──────────────┴──────────────┴──────────────┴──────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## 1. 核心数据结构

### 1.1 实体标识 (Entity ID)

```go
// EntityID - 32位实体标识
// 高8位: 类型 (角色/召唤物/支援/状态)
// 低24位: 序号
type EntityID uint32

const (
    EntityCharacter EntityID = 0x01 << 24
    EntitySummon    EntityID = 0x02 << 24
    EntitySupport   EntityID = 0x03 << 24
    EntityToken     EntityID = 0x04 << 24
)

func (e EntityID) Type() uint8 { return uint8(e >> 24) }
func (e EntityID) Index() uint32 { return uint32(e & 0xFFFFFF) }

// 特殊ID
const (
    EntityNone   EntityID = 0
    EntitySelf   EntityID = 0xFFFFFFFF // 技能释放者
    EntityActive EntityID = 0xFFFFFFFE // 当前出战角色
    EntityAll    EntityID = 0xFFFFFFFD // 所有目标
)
```

### 1.2 组件 (Components) - 纯数据

```go
// Component 接口标记
type Component interface {
    ComponentType() ComponentType
}

// HPComponent - 生命值
type HPComponent struct {
    Current uint8
    Max     uint8
}
func (HPComponent) ComponentType() ComponentType { return CompHP }

// EnergyComponent - 能量
type EnergyComponent struct {
    Current uint8
    Max     uint8
}

// ElementComponent - 元素属性
type ElementComponent struct {
    Character Element // 角色元素
    Aura      Element // 附着元素
    AuraDur   uint8   // 附着剩余次数
}

// SkillComponent - 技能
type SkillComponent struct {
    Skills []SkillDef
}

type SkillDef struct {
    ID       string
    Name     string
    Type     SkillType // Normal/Elemental/Burst
    Cost     Cost
    LuaScript string   // Lua脚本路径或代码
}

// SummonComponent - 召唤物标记
type SummonComponent struct {
    Owner    EntityID
    Uses     uint8
    MaxUses  uint8
    Trigger  Phase // 触发阶段
}

// TokenComponent - 状态层数
type TokenComponent struct {
    Tokens []Token
}

type Token struct {
    ID      string  // token类型ID
    Stacks  uint8   // 层数
    MaxStacks uint8 // 最大层数
    Source  EntityID
    Expire  uint8   // 过期回合（0=永久）
}

// PassiveComponent - 被动技能
type PassiveComponent struct {
    Triggers []PassiveTrigger
}

type PassiveTrigger struct {
    Event   EventType
    Filter  FilterFunc  // 条件过滤
    Action  string      // Lua函数名
}

// DamageModComponent - 伤害修改器（用于元素转换等）
type DamageModComponent struct {
    Modifiers []DamageModifier
}

type DamageModifier struct {
    Priority int
    Apply    func(ctx *DamageContext) // 修改伤害类型/数值
}
```

### 1.3 世界状态

```go
// World - 完整游戏状态
type World struct {
    Entities    map[EntityID]Entity
    Components  map[ComponentType]map[EntityID]Component
    
    // 阶段相关
    CurrentPhase Phase
    CurrentSide  uint8
    Round        uint8
    
    // 事件队列
    Events []Event
    
    // 查询缓存
    queryCache map[Query][]EntityID
}

// Entity - 实体是组件的容器
type Entity struct {
    ID         EntityID
    Components map[ComponentType]struct{}
}
```

## 2. 查询系统 (Query System)

```go
// Query - 实体查询
type Query struct {
    All  []ComponentType  // 必须包含所有
    Any  []ComponentType  // 包含任意一个
    None []ComponentType  // 不能包含
    Filter func(EntityID, *World) bool
}

// 预定义查询
var (
    QueryActiveCharacter = Query{
        All: []ComponentType{CompHP, CompElement},
        Filter: func(e EntityID, w *World) bool {
            // 是当前出战角色
            side := w.GetSide(e)
            active := w.GetActiveCharacter(side)
            return e == active
        },
    }
    
    QuerySummons = Query{
        All: []ComponentType{CompSummon},
    }
    
    QueryTokens = Query{
        All: []ComponentType{CompToken},
    }
)

// Query 实现
func (w *World) Query(q Query) []EntityID {
    // 缓存检查
    if cache, ok := w.queryCache[q]; ok {
        return cache
    }
    
    var results []EntityID
    for eid := range w.Entities {
        if w.matches(eid, q) {
            results = append(results, eid)
        }
    }
    
    // 缓存结果
    w.queryCache[q] = results
    return results
}

// GetComponent 类型安全获取
func GetComponent[T Component](w *World, e EntityID) (T, bool) {
    var zero T
    compType := zero.ComponentType()
    
    if m, ok := w.Components[compType]; ok {
        if c, ok := m[e]; ok {
            return c.(T), true
        }
    }
    return zero, false
}
```

## 3. 事件系统

```go
// Event 接口
type Event interface {
    Type() EventType
    Source() EntityID
}

// 事件类型
const (
    EventUseSkill EventType = iota
    EventDealDamage
    EventTakeDamage
    EventElementAttach
    EventElementReaction
    EventSummon
    EventTokenAdd
    EventTokenRemove
    EventPhaseChange
    EventCharacterSwitch
    EventDeath
)

// 具体事件定义

type UseSkillEvent struct {
    SourceEntity EntityID
    SkillID      string
    Targets      []EntityID
}

type DamageEvent struct {
    Source   EntityID
    Target   EntityID
    Amount   uint8
    Element  Element
    IsPiercing bool
    // 可被修改的字段
    FinalAmount uint8
}

type TokenChangeEvent struct {
    Target EntityID
    TokenID string
    OldStacks uint8
    NewStacks uint8
    Source EntityID
}
```

## 4. 系统实现

### 4.1 SkillSystem - 技能执行

```go
type SkillSystem struct {
    lua *LuaRuntime
}

func (s *SkillSystem) Execute(w *World, caster EntityID, skillID string, targets []EntityID) error {
    // 1. 获取技能定义
    skillComp, ok := GetComponent[SkillComponent](w, caster)
    if !ok {
        return fmt.Errorf("no skill component")
    }
    
    var skill *SkillDef
    for _, s := range skillComp.Skills {
        if s.ID == skillID {
            skill = &s
            break
        }
    }
    if skill == nil {
        return fmt.Errorf("skill not found: %s", skillID)
    }
    
    // 2. 构建技能上下文
    ctx := &SkillContext{
        World:   w,
        Caster:  caster,
        Targets: targets,
        Skill:   skill,
    }
    
    // 3. 执行 Lua 脚本
    effects, err := s.lua.ExecuteSkill(skill.LuaScript, ctx)
    if err != nil {
        return err
    }
    
    // 4. 应用效果（Go层执行）
    for _, eff := range effects {
        if err := s.applyEffect(w, eff); err != nil {
            return err
        }
    }
    
    // 5. 触发事件
    w.Events = append(w.Events, UseSkillEvent{
        SourceEntity: caster,
        SkillID:      skillID,
        Targets:      targets,
    })
    
    return nil
}
```

### 4.2 DamageSystem - 伤害计算

```go
type DamageSystem struct{}

func (s *DamageSystem) Calculate(w *World, e *DamageEvent) {
    // 1. 应用伤害修改器
    if modComp, ok := GetComponent[DamageModComponent](w, e.Source); ok {
        for _, mod := range modComp.Modifiers {
            mod.Apply(e)
        }
    }
    
    // 2. 元素反应
    targetElem, ok := GetComponent[ElementComponent](w, e.Target)
    if ok && targetElem.Aura != 0 && e.Element != 0 {
        reaction, multiplier := CalcReaction(e.Element, targetElem.Aura)
        e.FinalAmount = uint8(float32(e.Amount) * multiplier)
        
        // 触发反应事件
        w.Events = append(w.Events, ElementReactionEvent{
            Source:    e.Source,
            Target:    e.Target,
            Reaction:  reaction,
            Element:   e.Element,
            Aura:      targetElem.Aura,
        })
        
        // 清除附着
        targetElem.Aura = 0
        w.SetComponent(e.Target, targetElem)
    } else {
        e.FinalAmount = e.Amount
    }
    
    // 3. 护盾减免
    e.FinalAmount = s.applyShield(w, e.Target, e.FinalAmount)
    
    // 4. 应用伤害
    if hp, ok := GetComponent[HPComponent](w, e.Target); ok {
        if e.FinalAmount >= hp.Current {
            hp.Current = 0
            // 触发死亡
            w.Events = append(w.Events, DeathEvent{Entity: e.Target})
        } else {
            hp.Current -= e.FinalAmount
        }
        w.SetComponent(e.Target, hp)
    }
}
```

### 4.3 PhaseSystem - 阶段管理

```go
type PhaseSystem struct{}

func (s *PhaseSystem) ProcessPhase(w *World) {
    switch w.CurrentPhase {
    case PhaseRoll:
        s.processRollPhase(w)
    case PhaseAction:
        s.processActionPhase(w)
    case PhaseEnd:
        s.processEndPhase(w)
    }
}

func (s *PhaseSystem) processEndPhase(w *World) {
    // 1. 处理召唤物
    summons := w.Query(QuerySummons)
    for _, sid := range summons {
        summon, _ := GetComponent[SummonComponent](w, sid)
        if summon.Trigger == PhaseEnd {
            // 执行召唤物效果
            s.executeSummonEffect(w, sid)
            
            // 减少可用次数
            summon.Uses--
            if summon.Uses == 0 {
                w.RemoveEntity(sid)
            } else {
                w.SetComponent(sid, summon)
            }
        }
    }
    
    // 2. 清理过期token
    s.cleanupTokens(w)
    
    // 3. 切换回合
    w.Round++
    w.CurrentSide = 1 - w.CurrentSide
    w.CurrentPhase = PhaseRoll
}
```

### 4.4 TokenSystem - 状态层数

```go
type TokenSystem struct{}

func (s *TokenSystem) AddToken(w *World, target EntityID, tokenID string, stacks uint8, source EntityID) {
    tokenComp, ok := GetComponent[TokenComponent](w, target)
    if !ok {
        tokenComp = TokenComponent{}
    }
    
    // 查找是否已存在
    for i := range tokenComp.Tokens {
        if tokenComp.Tokens[i].ID == tokenID {
            old := tokenComp.Tokens[i].Stacks
            // 叠加层数
            tokenComp.Tokens[i].Stacks = min(
                tokenComp.Tokens[i].Stacks + stacks,
                tokenComp.Tokens[i].MaxStacks,
            )
            
            // 触发事件
            w.Events = append(w.Events, TokenChangeEvent{
                Target:    target,
                TokenID:   tokenID,
                OldStacks: old,
                NewStacks: tokenComp.Tokens[i].Stacks,
                Source:    source,
            })
            
            w.SetComponent(target, tokenComp)
            return
        }
    }
    
    // 新增token
    tokenComp.Tokens = append(tokenComp.Tokens, Token{
        ID:     tokenID,
        Stacks: stacks,
        Source: source,
    })
    w.SetComponent(target, tokenComp)
}

func (s *TokenSystem) ConsumeToken(w *World, target EntityID, tokenID string, stacks uint8) uint8 {
    tokenComp, ok := GetComponent[TokenComponent](w, target)
    if !ok {
        return 0
    }
    
    for i := range tokenComp.Tokens {
        if tokenComp.Tokens[i].ID == tokenID {
            consumed := min(stacks, tokenComp.Tokens[i].Stacks)
            tokenComp.Tokens[i].Stacks -= consumed
            
            if tokenComp.Tokens[i].Stacks == 0 {
                // 移除token
                tokenComp.Tokens = append(tokenComp.Tokens[:i], tokenComp.Tokens[i+1:]...)
            }
            
            w.SetComponent(target, tokenComp)
            return consumed
        }
    }
    return 0
}

func (s *TokenSystem) GetTokenStacks(w *World, target EntityID, tokenID string) uint8 {
    tokenComp, ok := GetComponent[TokenComponent](w, target)
    if !ok {
        return 0
    }
    for _, t := range tokenComp.Tokens {
        if t.ID == tokenID {
            return t.Stacks
        }
    }
    return 0
}
```

## 5. Lua 运行时

```go
type LuaRuntime struct {
    L *lua.State
}

// 暴露给 Lua 的 API
type WorldAPI struct {
    world *World
}

func (api *WorldAPI) DealDamage(target EntityID, amount uint8, element Element) {
    // 创建伤害事件，由DamageSystem处理
    api.world.Events = append(api.world.Events, &DamageEvent{
        Target:  target,
        Amount:  amount,
        Element: element,
    })
}

func (api *WorldAPI) AddToken(target EntityID, tokenID string, stacks uint8) {
    sys := &TokenSystem{}
    sys.AddToken(api.world, target, tokenID, stacks, EntitySelf)
}

func (api *WorldAPI) GetTokenStacks(target EntityID, tokenID string) uint8 {
    sys := &TokenSystem{}
    return sys.GetTokenStacks(api.world, target, tokenID)
}

func (api *WorldAPI) ConsumeToken(target EntityID, tokenID string, stacks uint8) uint8 {
    sys := &TokenSystem{}
    return sys.ConsumeToken(api.world, target, tokenID, stacks)
}

func (api *WorldAPI) QueryTargets(queryType string) []EntityID {
    switch queryType {
    case "active_enemy":
        // 返回敌方出战角色
        side := api.world.GetOppositeSide()
        return []EntityID{api.world.GetActiveCharacter(side)}
    case "all_enemies":
        // 返回所有敌方角色
        side := api.world.GetOppositeSide()
        return api.world.GetCharacters(side)
    case "self":
        return []EntityID{EntitySelf}
    default:
        return nil
    }
}
```

## 6. 角色实现示例

### 6.1 菲谢尔（简单召唤）

```lua
-- 菲谢尔 - 元素战技: 夜巡影翼
function use_skill(ctx)
    local effects = {}
    
    -- 造成1点雷元素伤害
    table.insert(effects, {
        type = "damage",
        target = ctx.targets[1],
        amount = 1,
        element = "electro"
    })
    
    -- 召唤奥兹
    table.insert(effects, {
        type = "summon",
        summon_id = "oz",
        owner = ctx.caster,
        uses = 2,
        trigger = "end_phase",
        effect = {
            type = "damage",
            target = "active_enemy",
            amount = 1,
            element = "electro"
        }
    })
    
    return effects
end

return use_skill(ctx)
```

### 6.2 阿蕾奇诺（复杂层数）

```lua
-- 阿蕾奇诺 - 被动: 战斗开始时
function on_battle_start(ctx)
    local effects = {}
    
    -- 在敌方场上生成3层血偿勒令
    local enemies = ctx.api:QueryTargets("all_enemies")
    for _, enemy in ipairs(enemies) do
        table.insert(effects, {
            type = "add_token",
            target = enemy,
            token_id = "blood_debt",
            stacks = 3
        })
    end
    
    return effects
end

-- 普通攻击: 斩首之邀
function normal_attack(ctx)
    local effects = {}
    local target = ctx.targets[1]
    
    -- 基础伤害
    local damage = 2
    
    -- 查询目标的生命之契层数
    local stacks = ctx.api:GetTokenStacks(target, "life_debt")
    if stacks > 0 then
        -- 消耗最多3层，提高等量伤害
        local consume = math.min(stacks, 3)
        local actual = ctx.api:ConsumeToken(target, "life_debt", consume)
        damage = damage + actual
    end
    
    -- 伤害类型转换检查（被动效果）
    local self_tokens = ctx.api:GetTokenStacks(ctx.caster, "life_debt")
    local element = "physical"
    if self_tokens > 0 then
        element = "pyro"  -- 有生命之契时转为火元素
    end
    
    table.insert(effects, {
        type = "damage",
        target = target,
        amount = damage,
        element = element
    })
    
    return effects
end

-- 元素爆发: 厄月将升
function elemental_burst(ctx)
    local effects = {}
    
    -- 造成4点火元素伤害
    table.insert(effects, {
        type = "damage",
        target = ctx.targets[1],
        amount = 4,
        element = "pyro"
    })
    
    -- 移除自身所有生命之契，每移除1层治疗1点
    local self_stacks = ctx.api:GetTokenStacks(ctx.caster, "life_debt")
    if self_stacks > 0 then
        ctx.api:ConsumeToken(ctx.caster, "life_debt", self_stacks)
        table.insert(effects, {
            type = "heal",
            target = ctx.caster,
            amount = self_stacks
        })
    end
    
    return effects
end

-- 被动: 唯厄月可知晓
function on_heal(ctx, heal_event)
    -- 如果治疗来源不是自己的元素爆发，则阻止
    if heal_event.source ~= ctx.caster then
        return {type = "prevent"}
    end
    return nil
end

-- 被动: 伤害类型转换
function on_damage_calc(ctx, damage_event)
    -- 如果有生命之契且是物理伤害，转为火元素
    local stacks = ctx.api:GetTokenStacks(ctx.caster, "life_debt")
    if stacks > 0 and damage_event.element == "physical" then
        damage_event.element = "pyro"
    end
    return damage_event
end

return _G[ctx.skill_name](ctx)
```

### 6.3 甘雨（多目标伤害）

```lua
-- 甘雨 - 元素爆发: 降众天华
function elemental_burst(ctx)
    local effects = {}
    
    -- 造成2点冰元素伤害
    table.insert(effects, {
        type = "damage",
        target = ctx.targets[1],
        amount = 2,
        element = "cryo"
    })
    
    -- 对敌方后台角色造成1点穿透伤害
    local enemies = ctx.api:QueryTargets("back_enemies")  -- 后台角色
    for _, enemy in ipairs(enemies) do
        table.insert(effects, {
            type = "damage",
            target = enemy,
            amount = 1,
            element = "piercing"  -- 穿透伤害
        })
    end
    
    -- 召唤冰灵珠
    table.insert(effects, {
        type = "summon",
        summon_id = "ice_lotus",
        owner = ctx.caster,
        uses = 2,
        trigger = "end_phase",
        effect = {
            type = "damage",
            target = "active_enemy",
            amount = 2,
            element = "cryo"
        }
    })
    
    return effects
end

return elemental_burst(ctx)
```

## 7. 动作验证系统

```go
type ValidActionSystem struct{}

func (s *ValidActionSystem) GetValidActions(w *World, side uint8) []Action {
    var actions []Action
    
    // 获取当前出战角色
    active := w.GetActiveCharacter(side)
    
    // 检查技能
    if skillComp, ok := GetComponent[SkillComponent](w, active); ok {
        for _, skill := range skillComp.Skills {
            // 检查费用
            if s.canAfford(w, side, skill.Cost) {
                actions = append(actions, Action{
                    Type: ActionUseSkill,
                    Params: map[string]interface{}{
                        "character": active,
                        "skill":     skill.ID,
                    },
                })
            }
        }
    }
    
    // 检查切换角色
    chars := w.GetCharacters(side)
    for _, char := range chars {
        if char != active {
            // 检查是否有快速行动token
            if s.hasFastActionToken(w, side) {
                actions = append(actions, Action{
                    Type: ActionSwitchFast,
                    Params: map[string]interface{}{"target": char},
                })
            } else {
                actions = append(actions, Action{
                    Type: ActionSwitch,
                    Params: map[string]interface{}{"target": char},
                })
            }
        }
    }
    
    // 检查手牌
    // ...
    
    // 结束回合总是可选
    actions = append(actions, Action{Type: ActionEndTurn})
    
    return actions
}
```

## 8. RL 接口

```go
// RL 观察值编码
type RLEncoder struct{}

func (e *RLEncoder) Encode(w *World, playerSide uint8) []float32 {
    var obs []float32
    
    // 1. 我方角色 (3个)
    myChars := w.GetCharacters(playerSide)
    for _, char := range myChars {
        hp, _ := GetComponent[HPComponent](w, char)
        energy, _ := GetComponent[EnergyComponent](w, char)
        elem, _ := GetComponent[ElementComponent](w, char)
        tokens, _ := GetComponent[TokenComponent](w, char)
        
        obs = append(obs,
            float32(hp.Current)/30.0,
            float32(energy.Current)/5.0,
            float32(elem.Aura),
            float32(len(tokens.Tokens)),
        )
    }
    
    // 2. 敌方角色 (公开信息)
    oppSide := 1 - playerSide
    oppChars := w.GetCharacters(oppSide)
    for _, char := range oppChars {
        hp, _ := GetComponent[HPComponent](w, char)
        elem, _ := GetComponent[ElementComponent](w, char)
        // 敌方能量不可见
        obs = append(obs,
            float32(hp.Current)/30.0,
            float32(elem.Aura),
        )
    }
    
    // 3. 召唤物
    summons := w.Query(QuerySummons)
    obs = append(obs, float32(len(summons))/4.0)
    
    // 4. 骰子
    dice := w.GetDice(playerSide)
    for _, count := range dice {
        obs = append(obs, float32(count)/16.0)
    }
    
    return obs
}
```

---

## 架构优势

1. **ECS 模式**: 数据与逻辑分离，便于序列化和状态拷贝
2. **事件驱动**: 被动技能和触发效果自然实现
3. **查询系统**: 复杂条件查询（如"所有后台角色"）易于表达
4. **Lua 脚本**: 角色效果灵活配置，热更新友好
5. **组件化**: 新机制只需添加新组件和系统
