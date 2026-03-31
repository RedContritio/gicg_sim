# Mod 系统架构设计

## 核心思想

> **角色 = 基础属性 + Mod 列表**
> 
> **任何效果都是 "条件下触发"**

```
传统 ECS:                          Mod 系统:
Entity + Components                 Character + Mods
  - HPComponent                      - base_hp: 10
  - SkillComponent                   - mods: [...]
  - TokenComponent
  - PassiveComponent

Mod 是 "带有生命周期的状态 + 触发逻辑"
```

## 1. 基础结构

```go
// Character - 角色
type Character struct {
    ID        string
    Name      string
    HP        int
    MaxHP     int
    Energy    int
    MaxEnergy int
    Element   Element
    
    Mods []Mod  // 关键：所有状态都在这里
}

// Mod - 修改器
type Mod struct {
    ID       string      // 唯一标识，如 "diluc_e_combo"
    Source   string      // 来源技能/卡牌
    Type     ModType     // 计数器/状态/触发器
    
    // 生命周期
    Duration int         // 持续回合 (0=永久, -1=立即生效后移除)
    Uses     int         // 可用次数
    
    // 数据
    Data map[string]interface{}
    
    // 触发逻辑 (可选)
    Triggers []Trigger
}

type ModType int
const (
    ModCounter ModType = iota  // 计数器，如 "E技能使用次数"
    ModStatus                  // 状态标记，如 "火元素附魔"
    ModTrigger                 // 触发器，如 "结束阶段造成伤害"
    ModShield                  // 护盾
)

// Trigger - 触发器
type Trigger struct {
    Event   string          // 事件类型
    Condition Condition    // 条件
    Action  Action          // 执行动作
}
```

## 2. 迪卢克 E 技能实现

```go
// 迪卢克 E 技能 (逆焰之刃)
// 效果: 3段攻击，第3段伤害+2

// 方案: 使用计数器 Mod
var DilucESkill = Skill{
    ID: "diluc_e",
    Cost: Cost{Pyro: 3},
    
    OnUse: func(ctx *Context) []Effect {
        combo := ctx.GetModCounter(ctx.Caster, "diluc_e_combo")
        
        var dmg int
        if combo >= 2 {
            dmg = 5  // 第3段
        } else {
            dmg = 3  // 第1、2段
        }
        
        effects := []Effect{
            Damage(ctx.Target, dmg, Pyro),
        }
        
        // 增加计数器
        if combo >= 2 {
            // 第3段，重置
            effects = append(effects, 
                RemoveMod(ctx.Caster, "diluc_e_combo"))
        } else {
            // 第1、2段，累加
            effects = append(effects, 
                AddOrIncMod(ctx.Caster, "diluc_e_combo", 1, Mod{
                    ID: "diluc_e_combo",
                    Type: ModCounter,
                    Duration: -1,  // 本回合有效
                }))
        }
        
        return effects
    },
}

// 或者更简洁的 Mod 定义方式
var DilucEComboMod = Mod{
    ID: "diluc_e_combo",
    Type: ModCounter,
    OnEvent: func(evt Event, mod *Mod, ctx *Context) []Effect {
        // 回合结束时自动清理
        if evt.Type == "round_end" {
            return []Effect{RemoveMod(mod.Owner, mod.ID)}
        }
        return nil
    },
}
```

## 3. 各种机制的实现

### 3.1 护盾 (迪奥娜)

```go
// 猫爪护盾 Mod
var CatClawShieldMod = Mod{
    ID: "cat_claw_shield",
    Type: ModShield,
    Data: map[string]interface{}{
        "shield_value": 2,  // 可抵挡2点伤害
    },
    Duration: -1,  // 次数耗尽后移除
    Uses: 2,       // 可用2次
    
    OnEvent: func(evt Event, mod *Mod, ctx *Context) []Effect {
        // 受到伤害时
        if evt.Type == "on_damage_receive" {
            dmg := evt.Data["amount"].(int)
            shield := mod.Data["shield_value"].(int)
            
            if shield >= dmg {
                // 完全抵挡
                mod.Data["shield_value"] = shield - dmg
                mod.Uses--
                return []Effect{
                    BlockDamage(evt.Target, dmg),
                    If(mod.Uses <= 0, RemoveMod(mod.Owner, mod.ID)),
                }
            } else {
                // 部分抵挡
                mod.Uses = 0
                return []Effect{
                    BlockDamage(evt.Target, shield),
                    RemoveMod(mod.Owner, mod.ID),
                    DealDamage(evt.Target, dmg - shield),
                }
            }
        }
        return nil
    },
}
```

### 3.2 召唤物 (菲谢尔奥兹)

```go
// 奥兹 Mod
var OzMod = Mod{
    ID: "oz_summon",
    Type: ModTrigger,
    Uses: 2,  // 触发2次后消失
    
    Triggers: []Trigger{
        {
            Event: "phase_end",
            Condition: Condition{Phase: EndPhase},
            Action: Action{
                Type: ActionDealDamage,
                Target: TargetActiveEnemy,
                Amount: 1,
                Element: Electro,
            },
        },
    },
}

// 菲谢尔 E 技能
var FischlESkill = Skill{
    ID: "fischl_e",
    OnUse: func(ctx *Context) []Effect {
        return []Effect{
            Damage(ctx.Target, 1, Electro),
            AddMod(ctx.Caster, OzMod),  // 添加奥兹
        }
    },
}
```

### 3.3 Token 层数 (阿蕾奇诺)

```go
// 生命之契 Mod
var LifeDebtMod = Mod{
    ID: "life_debt",
    Type: ModCounter,
    // 层数就是 Data["stacks"]
}

// 阿蕾奇诺普攻
var ArlecchinoAttack = Skill{
    ID: "arlecchino_attack",
    OnUse: func(ctx *Context) []Effect {
        // 查询自身生命之契
        debt := ctx.GetModStacks(ctx.Caster, "life_debt")
        
        dmg := 2
        element := Physical
        
        if debt > 0 {
            element = Pyro  // 有生命之契时转为火伤
        }
        
        // 查询敌方血偿勒令
        enemyDebt := ctx.GetModStacks(ctx.Target, "blood_debt")
        if enemyDebt > 0 {
            consume := Min(enemyDebt, 3)
            dmg += consume
        }
        
        return []Effect{
            Damage(ctx.Target, dmg, element),
            If(enemyDebt > 0, 
                ConsumeMod(ctx.Target, "blood_debt", Min(enemyDebt, 3))),
        }
    },
}

// 被动: 战斗开始时给敌方添加血偿勒令
var ArlecchinoPassive = Mod{
    ID: "arlecchino_passive",
    Type: ModTrigger,
    Triggers: []Trigger{
        {
            Event: "battle_start",
            Action: Action{
                Type: ActionAddMod,
                Target: TargetAllEnemies,
                Mod: Mod{
                    ID: "blood_debt",
                    Type: ModCounter,
                    Data: map[string]interface{}{"stacks": 3},
                },
            },
        },
    },
}
```

### 3.4 元素附魔 (迪卢克大招后)

```go
// 火元素附魔 Mod
var PyroInfusionMod = Mod{
    ID: "pyro_infusion",
    Type: ModStatus,
    Duration: 2,  // 持续2回合
    
    OnEvent: func(evt Event, mod *Mod, ctx *Context) []Effect {
        // 普攻伤害类型转换
        if evt.Type == "on_damage_calc" && evt.SkillType == NormalAttack {
            if evt.Element == Physical {
                evt.Element = Pyro
                evt.Amount += 1  // 附魔伤害+1
            }
        }
        return nil
    },
}
```

## 4. Mod 生命周期管理

```go
// PhaseSystem 在阶段转换时处理 Mod
type PhaseSystem struct{}

func (s *PhaseSystem) OnPhaseEnd(w *World) {
    for _, char := range w.AllCharacters() {
        for i := len(char.Mods) - 1; i >= 0; i-- {
            mod := &char.Mods[i]
            
            // 1. 触发 Mod 的阶段事件
            for _, trigger := range mod.Triggers {
                if trigger.Event == "phase_end" {
                    effects := trigger.Execute(w, mod)
                    w.ApplyEffects(effects)
                }
            }
            
            // 2. 减少持续回合
            if mod.Duration > 0 {
                mod.Duration--
                if mod.Duration == 0 {
                    // 移除过期 Mod
                    char.Mods = append(char.Mods[:i], char.Mods[i+1:]...)
                    continue
                }
            }
            
            // 3. 检查次数耗尽
            if mod.Uses == 0 {
                char.Mods = append(char.Mods[:i], char.Mods[i+1:]...)
            }
        }
    }
}
```

## 5. Lua 绑定 (简化)

```lua
-- 技能脚本只描述 "添加什么 Mod" 和 "基础效果"
-- 复杂的触发逻辑在 Mod 定义中

-- 迪卢克 E 技能 (Lua)
function skill(ctx)
    local combo = ctx:get_mod_counter("diluc_e_combo") or 0
    
    local dmg = 3
    if combo >= 2 then
        dmg = 5
    end
    
    local effects = {
        {type="damage", amount=dmg, element="pyro"},
    }
    
    -- 添加/更新计数器 Mod
    if combo >= 2 then
        table.insert(effects, {type="remove_mod", id="diluc_e_combo"})
    else
        table.insert(effects, {
            type="add_mod", 
            mod={
                id="diluc_e_combo",
                type="counter",
                value=combo+1,
                duration=-1  -- 回合结束清除
            }
        })
    end
    
    return effects
end

-- 奥兹召唤 (Lua)
function summon_oz(ctx)
    return {
        {type="damage", amount=1, element="electro"},
        {type="add_mod", mod={
            id="oz",
            type="trigger",
            uses=2,
            triggers={{
                event="end_phase",
                action={type="damage", target="active_enemy", amount=1, element="electro"}
            }}
        }},
    }
end
```

## 6. 与 RL 观察值结合

```go
// 编码角色状态 (包括 Mods)
func (e *RLEncoder) EncodeCharacter(char *Character) []float32 {
    var obs []float32
    
    // 基础属性
    obs = append(obs, float32(char.HP)/30.0)
    obs = append(obs, float32(char.Energy)/5.0)
    
    // Mod 编码 (固定维度)
    // 每种 ModType 预留N个槽位
    
    // 计数器槽位 (4个)
    counterObs := make([]float32, 4*2)  // [id, value] * 4
    idx := 0
    for _, mod := range char.Mods {
        if mod.Type == ModCounter && idx < 8 {
            counterObs[idx] = float32(hashModID(mod.ID) % 100) / 100.0  // ID编码
            counterObs[idx+1] = float32(mod.Data["stacks"].(int)) / 10.0  // 层数
            idx += 2
        }
    }
    obs = append(obs, counterObs...)
    
    // 触发器槽位 (2个)
    triggerObs := make([]float32, 2*2)
    idx = 0
    for _, mod := range char.Mods {
        if mod.Type == ModTrigger && idx < 4 {
            triggerObs[idx] = float32(hashModID(mod.ID) % 100) / 100.0
            triggerObs[idx+1] = float32(mod.Uses) / 5.0  // 剩余次数
            idx += 2
        }
    }
    obs = append(obs, triggerObs...)
    
    return obs
}
```

## 7. 优势对比

| 方面 | ECS | Mod 系统 |
|------|-----|----------|
| 概念复杂度 | Entity+Component+System | Character+Mod |
| 状态管理 | 分散在多个Component | 集中在 Mods 列表 |
| 生命周期 | 需单独处理 | Duration/Uses 自动管理 |
| 触发逻辑 | EventBus 分发 | Mod 自带 Triggers |
| 代码量 | 多 | 少 |
| 可扩展性 | 好 | 足够 |

## 8. 完整示例：回合流程

```go
func (w *World) ExecuteTurn(action Action) {
    // 1. 执行动作
    switch action.Type {
    case ActionUseSkill:
        skill := w.GetSkill(action.SkillID)
        effects := skill.OnUse(&Context{
            Caster: action.Character,
            Target: w.GetActiveEnemy(),
        })
        w.ApplyEffects(effects)
    }
    
    // 2. 结算伤害 (触发 on_damage 相关 Mod)
    w.ProcessDamageQueue()
    
    // 3. 结束阶段 (触发 end_phase Mods)
    w.PhaseSystem.OnPhaseEnd()
    
    // 4. 清理过期 Mod
    w.CleanupMods()
}
```

---

**总结**: Mod 系统比 ECS 更轻量，更适合卡牌游戏的"状态+触发"模型。
