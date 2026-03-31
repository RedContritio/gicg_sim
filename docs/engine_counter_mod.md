# Counter + Mod 分离架构

## 核心思想

> **Counter 存状态，Mod 存逻辑，彻底解耦。**

```
传统 Mod:                         分离设计:
Mod{
    ID: "oz",                     Counter{
    Type: ModTrigger,                 ID: "fischl_oz_uses",
    Uses: 2,                    -->     Value: 2
    Data: {...},                      }
    Triggers: [...],
}                                 
                                  Mod{
                                      ID: "fischl_oz_trigger",
                                      Event: "end_phase",
                                      Condition: "fischl_oz_uses > 0",
                                      Action: [
                                          "damage(active_enemy, 1, electro)",
                                          "dec_counter(fischl_oz_uses)"
                                      ],
                                  }
```

## 1. 数据结构

```go
// Side - 一方玩家
type Side struct {
    Characters [3]Character
    
    // 全局 Counter (双方可见/部分可见)
    Counters map[string]int
    
    // Mod 列表 (触发逻辑)
    Mods []Mod
}

// Counter - 纯数值状态
type Counter struct {
    ID    string  // 全名: "角色名_效果名_类型"
    Value int     // 当前值
    
    // 元数据 (用于RL观察值)
    Max   int     // 最大值 (用于归一化)
    Type  CounterType
}

type CounterType int
const (
    CounterUses      CounterType = iota  // 可用次数 (如奥兹)
    CounterStacks                        // 层数 (如生命之契)
    CounterCombo                         // 连击计数 (如迪卢克E)
    CounterResource                      // 资源 (如夜魂值)
)

// Mod - 纯触发逻辑，无状态
type Mod struct {
    ID        string
    Source    string      // 来源角色/卡牌
    
    Event     string      // 触发事件
    Condition Condition   // 条件 (可选)
    Actions   []string    // 执行动作 (Lua表达式)
    
    Priority  int         // 优先级 (用于排序)
}

// Condition - 条件表达式
type Condition struct {
    Expr string  // 如 "counter(fischl_oz_uses) > 0"
}
```

## 2. 菲谢尔完整实现

```go
// 菲谢尔角色配置
var Fischl = CharacterDef{
    ID: "fischl",
    Name: "菲谢尔",
    HP: 10,
    Element: Electro,
    
    // 初始 Setup
    Setup: func(side *Side) {
        // 初始化 Counter (不在这里，在首次使用时创建)
    },
    
    Skills: []Skill{
        {
            ID: "fischl_e",
            Name: "夜巡影翼",
            Cost: Cost{Electro: 3},
            
            OnUse: func(ctx *Context) []Action {
                return []Action{
                    // 1. 造成1点雷伤
                    {Type: ActionDamage, Target: TargetActiveEnemy, Amount: 1, Element: Electro},
                    
                    // 2. 设置奥兹 Counter (可用2次)
                    {Type: ActionSetCounter, Counter: "fischl_oz_uses", Value: 2, Max: 2},
                    
                    // 3. 添加 Mod (如果还没有)
                    {Type: ActionAddMod, Mod: OzTriggerMod},
                }
            },
        },
    },
}

// 奥兹触发 Mod (纯逻辑，无状态)
var OzTriggerMod = Mod{
    ID: "fischl_oz_trigger",
    Source: "fischl",
    Event: "end_phase",
    Condition: Condition{Expr: "counter(fischl_oz_uses) > 0"},
    Actions: []string{
        "damage(active_enemy, 1, electro)",
        "dec_counter(fischl_oz_uses)",
        "if counter(fischl_oz_uses) == 0 then remove_mod(fischl_oz_trigger) end",
    },
}
```

## 3. 各种机制实现

### 3.1 迪卢克 E 技能 (连击)

```go
var DilucE = Skill{
    ID: "diluc_e",
    OnUse: func(ctx *Context) []Action {
        combo := ctx.GetCounter("diluc_e_combo") // 0, 1, 2
        
        dmg := 3
        if combo >= 2 {
            dmg = 5  // 第3段
        }
        
        actions := []Action{
            {Type: ActionDamage, Target: TargetActiveEnemy, Amount: dmg, Element: Pyro},
        }
        
        if combo >= 2 {
            // 第3段，重置计数器
            actions = append(actions, 
                Action{Type: ActionSetCounter, Counter: "diluc_e_combo", Value: 0})
        } else {
            // 第1、2段，累加
            actions = append(actions,
                Action{Type: ActionIncCounter, Counter: "diluc_e_combo", Delta: 1})
            
            // 添加回合结束清理 Mod (如果还没有)
            if !ctx.HasMod("diluc_e_reset") {
                actions = append(actions,
                    Action{Type: ActionAddMod, Mod: DilucEResetMod})
            }
        }
        
        return actions
    },
}

// 回合结束重置连击
var DilucEResetMod = Mod{
    ID: "diluc_e_reset",
    Event: "round_end",
    Actions: []string{
        "set_counter(diluc_e_combo, 0)",
        "remove_mod(diluc_e_reset)",
    },
}
```

### 3.2 阿蕾奇诺 (层数管理)

```go
var ArlecchinoPassive = Setup{
    OnBattleStart: func(ctx *Context) []Action {
        // 给每个敌方角色添加血偿勒令 Counter
        actions := []Action{}
        for _, enemy := range ctx.GetEnemies() {
            actions = append(actions,
                Action{Type: ActionSetCounter, Target: enemy, Counter: "blood_debt", Value: 3})
        }
        return actions
    },
}

var ArlecchinoAttack = Skill{
    ID: "arlecchino_attack",
    OnUse: func(ctx *Context) []Action {
        dmg := 2
        element := Physical
        
        // 检查自身生命之契
        if ctx.GetCounter("arlecchino_life_debt") > 0 {
            element = Pyro  // 转为火伤
        }
        
        // 检查敌方血偿勒令
        enemyDebt := ctx.GetCounterOn(ctx.Target, "blood_debt")
        if enemyDebt > 0 {
            consume := Min(enemyDebt, 3)
            dmg += consume
        }
        
        return []Action{
            {Type: ActionDamage, Target: ctx.Target, Amount: dmg, Element: element},
            If(enemyDebt > 0, 
                Action{Type: ActionDecCounter, Target: ctx.Target, Counter: "blood_debt", Delta: Min(enemyDebt, 3)}),
        }
    },
}
```

### 3.3 护盾 (数值型 Counter)

```go
// 迪奥娜 E 技能
var DionaE = Skill{
    ID: "diona_e",
    OnUse: func(ctx *Context) []Action {
        return []Action{
            {Type: ActionDamage, Target: TargetActiveEnemy, Amount: 2, Element: Cryo},
            // 护盾值作为 Counter
            {Type: ActionSetCounter, Counter: "diona_shield", Value: 2}, // 2点护盾
            // 添加伤害拦截 Mod
            {Type: ActionAddMod, Mod: ShieldBlockMod},
        }
    },
}

// 护盾拦截 Mod
var ShieldBlockMod = Mod{
    ID: "shield_block",
    Event: "on_damage_receive",
    // 这里用特殊机制: 拦截伤害并修改
    Handler: func(evt *DamageEvent) {
        shield := evt.Target.Side.GetCounter("diona_shield")
        if shield > 0 {
            block := Min(shield, evt.Amount)
            evt.Amount -= block  // 减少伤害
            evt.Target.Side.DecCounter("diona_shield", block)
            
            if evt.Target.Side.GetCounter("diona_shield") == 0 {
                evt.Target.Side.RemoveMod("shield_block")
            }
        }
    },
}
```

## 4. 事件处理流程

```go
func (w *World) TriggerEvent(event string, ctx *EventContext) {
    // 1. 收集所有相关 Mod
    var mods []Mod
    for _, side := range w.Sides {
        for _, mod := range side.Mods {
            if mod.Event == event {
                mods = append(mods, mod)
            }
        }
    }
    
    // 2. 按优先级排序
    sort.Slice(mods, func(i, j int) bool {
        return mods[i].Priority > mods[j].Priority
    })
    
    // 3. 依次执行
    for _, mod := range mods {
        // 检查条件
        if mod.Condition.Expr != "" {
            if !ctx.EvalCondition(mod.Condition.Expr) {
                continue
            }
        }
        
        // 执行动作
        for _, action := range mod.Actions {
            ctx.ExecuteAction(action)
        }
    }
}
```

## 5. RL 观察值编码

```go
func (e *RLEncoder) EncodeSide(side *Side) []float32 {
    var obs []float32
    
    // 1. 角色基础状态
    for _, char := range side.Characters {
        obs = append(obs, float32(char.HP)/30.0)
        obs = append(obs, float32(char.Energy)/5.0)
    }
    
    // 2. Counter 编码 (关键！)
    // 预定义关键 Counter 槽位
    counterSlots := []string{
        "fischl_oz_uses",
        "diluc_e_combo", 
        "arlecchino_life_debt",
        "blood_debt",
        // ... 更多
    }
    
    for _, counterID := range counterSlots {
        if val, ok := side.Counters[counterID]; ok {
            obs = append(obs, float32(val)/10.0)  // 归一化
        } else {
            obs = append(obs, 0.0)  // 不存在则为0
        }
    }
    
    // 3. Mod 存在性编码 (只编码有哪些 Mod 在生效)
    modSlots := []string{
        "fischl_oz_trigger",
        "shield_block",
        "element_infusion",
        // ...
    }
    
    for _, modID := range modSlots {
        if side.HasMod(modID) {
            obs = append(obs, 1.0)
        } else {
            obs = append(obs, 0.0)
        }
    }
    
    return obs
}

// 更紧凑的编码: Counter 和 Mod 配对
func (e *RLEncoder) EncodeCompact(side *Side) []float32 {
    var obs []float32
    
    // 每个角色6个槽位 (3 Counter + 3 Mod)
    for i := 0; i < 3; i++ {
        charID := side.Characters[i].ID
        
        // Counter 槽位
        for j := 0; j < 3; j++ {
            counterID := fmt.Sprintf("%s_counter_%d", charID, j)
            if val, ok := side.Counters[counterID]; ok {
                obs = append(obs, float32(val)/10.0)
            } else {
                obs = append(obs, -1.0)  // -1 表示不存在
            }
        }
        
        // Mod 存在性
        for j := 0; j < 3; j++ {
            modID := fmt.Sprintf("%s_mod_%d", charID, j)
            if side.HasMod(modID) {
                obs = append(obs, 1.0)
            } else {
                obs = append(obs, 0.0)
            }
        }
    }
    
    return obs
}
```

## 6. Lua 脚本示例

```lua
-- 菲谢尔 E 技能
function on_use(ctx)
    return {
        {type = "damage", target = "active_enemy", amount = 1, element = "electro"},
        {type = "set_counter", counter = "fischl_oz_uses", value = 2},
        {type = "add_mod", mod = "fischl_oz_trigger"},
    }
end

-- 奥兹触发 Mod (定义在配置中)
-- Mod: {
--     id = "fischl_oz_trigger",
--     event = "end_phase",
--     condition = "counter(fischl_oz_uses) > 0",
--     actions = {
--         "damage(active_enemy, 1, electro)",
--         "dec_counter(fischl_oz_uses)",
--     }
-- }

-- 阿蕾奇诺普攻
function on_use(ctx)
    local dmg = 2
    local element = "physical"
    
    -- 检查自身生命之契
    if ctx.get_counter("arlecchino_life_debt") > 0 then
        element = "pyro"
    end
    
    -- 检查目标血偿勒令
    local debt = ctx.get_counter_on(ctx.target, "blood_debt")
    if debt > 0 then
        local consume = math.min(debt, 3)
        dmg = dmg + consume
    end
    
    local actions = {
        {type = "damage", target = ctx.target, amount = dmg, element = element},
    }
    
    if debt > 0 then
        table.insert(actions, {
            type = "dec_counter", 
            target = ctx.target, 
            counter = "blood_debt", 
            delta = math.min(debt, 3)
        })
    end
    
    return actions
end
```

## 7. 优势总结

| 设计 | Counter+Mod 分离 | 传统一体 Mod |
|------|------------------|-------------|
| 状态位置 | 明确的 Counter 层 | Mod.Data 内部 |
| RL 观察 | 直接读取 Counter | 需解析 Mod |
| 逻辑复用 | Mod 可共享 Counter | 每个 Mod 独立 |
| 调试 | 查 Counter 值即可 | 需打印 Mod 结构 |
| 性能 | Counter 是 map 查表 | 遍历 Mod 列表 |

---

**核心设计**: Counter 是"数值状态"，Mod 是"触发逻辑"，两者通过 ID 关联。
