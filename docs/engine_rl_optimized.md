# RL 优化的 Lua 方案

## 核心思想

> **Lua 只配置，Go 执行。一次性调用，纯函数输出。**

```
传统方案 (慢):                    RL优化方案 (快):
SkillSystem -> Lua(执行)          SkillSystem
    |                                   |
    v (返回效果)                   Lua(预编译缓存)
Go执行效果                              |
    ^                                   v
Lua回调(查询状态)                执行模板(纯Go，无Lua)
    |                                   |
    +-----------------------------------+
```

## 1. 架构调整

### 1.1 预编译缓存

```go
// 技能模板 (预编译后缓存)
type SkillTemplate struct {
    SkillID string
    
    // 静态效果 (无条件)
    StaticEffects []Effect
    
    // 条件效果 (运行时再判断)
    ConditionalEffects []ConditionalEffect
    
    // 查询需求 (Go预先计算)
    RequiredQueries []QueryType
    
    // Lua字节码 (可选，用于复杂技能)
    LuaBytecode []byte
}

// 条件效果
type ConditionalEffect struct {
    Condition ConditionExpr  // 简单表达式
    Effects   []Effect       // 条件成立时的效果
}

// 条件表达式 (简单可序列化)
type ConditionExpr struct {
    Type string  // "has_token", "hp_lt", "has_aura", etc.
    Args []interface{}
}
```

### 1.2 运行时流程

```go
func (s *SkillSystem) Execute(w *World, caster EntityID, skillID string) {
    // 1. 获取预编译模板 (O(1) 查表)
    tmpl := s.templateCache[skillID]
    
    // 2. 执行静态效果
    for _, eff := range tmpl.StaticEffects {
        s.applyEffect(w, eff)
    }
    
    // 3. 批量查询 (一次查询多个条件)
    queryResults := s.batchQuery(w, tmpl.RequiredQueries, caster)
    
    // 4. 评估条件效果 (纯Go，无Lua)
    for _, ce := range tmpl.ConditionalEffects {
        if s.evalCondition(ce.Condition, queryResults) {
            for _, eff := range ce.Effects {
                s.applyEffect(w, eff)
            }
        }
    }
    
    // 5. 复杂逻辑才调用Lua (少数技能需要)
    if tmpl.LuaBytecode != nil {
        s.executeLuaAdvanced(w, tmpl, queryResults)
    }
}
```

## 2. Lua 简化方案

### 2.1 方案 A：声明式 JSON (推荐简单技能)

**不用 Lua，纯 JSON 配置：**

```json
{
  "skill_id": "fischl_skill",
  "name": "夜巡影翼",
  "cost": {"electro": 3},
  
  "effects": [
    {
      "type": "damage",
      "target": "active_enemy",
      "amount": 1,
      "element": "electro"
    },
    {
      "type": "summon",
      "summon_id": "oz",
      "uses": 2,
      "trigger": "end_phase",
      "trigger_effect": {
        "type": "damage",
        "target": "active_enemy",
        "amount": 1,
        "element": "electro"
      }
    }
  ]
}
```

**阿蕾奇诺普攻（条件效果）：**

```json
{
  "skill_id": "arlecchino_attack",
  "effects": [
    {
      "type": "damage",
      "target": "active_enemy",
      "amount": 2,
      "element": "physical"
    }
  ],
  
  "modifiers": [
    {
      "trigger": "on_damage_calc",
      "condition": {
        "type": "has_token",
        "target": "self",
        "token": "life_debt",
        "min_stacks": 1
      },
      "action": {
        "type": "change_element",
        "from": "physical",
        "to": "pyro"
      }
    },
    {
      "trigger": "on_damage_calc",
      "condition": {
        "type": "target_has_token",
        "token": "blood_debt"
      },
      "action": {
        "type": "consume_token_damage",
        "token": "blood_debt",
        "max_consume": 3,
        "damage_per_stack": 1
      }
    }
  ]
}
```

### 2.2 方案 B：简化 Lua (复杂技能)

**Lua 只读，返回纯数据，不回调 Go：**

```lua
-- 输入: Go 预先计算好的上下文
-- 输出: 纯效果列表

-- 阿蕾奇诺普攻 (简化版)
function skill(ctx)
    -- ctx 包含预计算的数据:
    -- ctx.self.tokens["life_debt"] = 2
    -- ctx.target.tokens["blood_debt"] = 3
    -- ctx.target.hp_percent = 0.8
    
    local effects = {}
    local damage = 2
    local element = "physical"
    
    -- 检查自己的生命之契
    if ctx.self.tokens["life_debt"] and ctx.self.tokens["life_debt"] > 0 then
        element = "pyro"
    end
    
    -- 检查目标的血偿勒令
    local debt = ctx.target.tokens["blood_debt"] or 0
    if debt > 0 then
        local consume = math.min(debt, 3)
        damage = damage + consume
        -- 添加消耗token的效果
        table.insert(effects, {
            type = "consume_token",
            target = "target",
            token = "blood_debt",
            amount = consume
        })
    end
    
    -- 基础伤害
    table.insert(effects, {
        type = "damage",
        target = "target",
        amount = damage,
        element = element
    })
    
    return effects
end

-- 注意: Lua 不直接操作世界，只返回数据
-- Go 负责执行这些效果
```

### 2.3 方案 C：完全预编译 (最高性能)

**技能完全编译为 Go 函数：**

```go
// 技能注册表
var SkillRegistry = map[string]SkillFunc{
    "fischl_skill": FischlSkill,
    "arlecchino_attack": ArlecchinoAttack,
    // ...
}

// 菲谢尔技能 (纯 Go，最高性能)
func FischlSkill(w *World, ctx *SkillContext) []Effect {
    return []Effect{
        {Type: EffDamage, Target: ctx.Targets[0], Amount: 1, Element: EleElectro},
        {Type: EffSummon, SummonID: "oz", Uses: 2, Trigger: PhaseEnd, 
         TriggerEffect: Effect{Type: EffDamage, Amount: 1, Element: EleElectro}},
    }
}

// 阿蕾奇诺普攻
func ArlecchinoAttack(w *World, ctx *SkillContext) []Effect {
    var effects []Effect
    damage := 2
    element := ElePhysical
    
    // 检查自己的生命之契
    if GetTokenStacks(w, ctx.Caster, "life_debt") > 0 {
        element = ElePyro
    }
    
    // 检查目标的血偿勒令
    target := ctx.Targets[0]
    debt := GetTokenStacks(w, target, "blood_debt")
    if debt > 0 {
        consume := min(debt, 3)
        damage += consume
        effects = append(effects, Effect{
            Type: EffConsumeToken, Target: target, TokenID: "blood_debt", Amount: consume,
        })
    }
    
    effects = append(effects, Effect{
        Type: EffDamage, Target: target, Amount: damage, Element: element,
    })
    
    return effects
}
```

## 3. 推荐方案：分层策略

```
┌─────────────────────────────────────────┐
│  Tier 1: 纯 JSON (80% 技能)              │
│  - 简单伤害/召唤/治疗                     │
│  - 无复杂条件                            │
│  - 性能: 最高                            │
├─────────────────────────────────────────┤
│  Tier 2: 简化 Lua (15% 技能)             │
│  - 有条件判断                            │
│  - 需要查询 Token/状态                    │
│  - 性能: 高 (单次调用)                    │
├─────────────────────────────────────────┤
│  Tier 3: 纯 Go 函数 (5% 技能)            │
│  - 极复杂逻辑                            │
│  - 核心角色/高频使用                      │
│  - 性能: 最高                            │
└─────────────────────────────────────────┘
```

### 实际角色分级示例

| 角色 | 复杂度 | 方案 | 理由 |
|------|--------|------|------|
| 菲谢尔 | 低 | JSON | 固定召唤+伤害 |
| 刻晴 | 低 | JSON | 纯伤害 |
| 甘雨 | 中 | JSON | 多目标+穿透 |
| 阿蕾奇诺 | 高 | Lua/Go | Token层数+伤害转换 |
| 芙宁娜 | 高 | Go | 双形态+全局光环 |
| 玛薇卡 | 极高 | Go | 夜魂机制复杂 |

## 4. 具体实现

### 4.1 JSON Schema

```go
// SkillConfig - JSON 配置结构
type SkillConfig struct {
    ID      string      `json:"skill_id"`
    Name    string      `json:"name"`
    Type    SkillType   `json:"type"` // Normal/Elemental/Burst
    Cost    CostConfig  `json:"cost"`
    
    // 基础效果
    Effects []EffectConfig `json:"effects"`
    
    // 修改器 (条件触发)
    Modifiers []ModifierConfig `json:"modifiers,omitempty"`
    
    // Lua脚本路径 (可选)
    LuaScript string `json:"lua_script,omitempty"`
    
    // 标记为Go原生实现
    NativeImpl string `json:"native_impl,omitempty"`
}

type EffectConfig struct {
    Type   string                 `json:"type"` // damage, heal, summon, token_add, etc.
    Target string                 `json:"target"` // self, target, active_enemy, all_enemies, etc.
    Params map[string]interface{} `json:"params"`
}

type ModifierConfig struct {
    Trigger   string          `json:"trigger"`   // on_damage_calc, on_phase_end, etc.
    Condition ConditionConfig `json:"condition"`
    Action    EffectConfig    `json:"action"`
}

type ConditionConfig struct {
    Type string                 `json:"type"` // has_token, hp_lt, has_aura, etc.
    Args map[string]interface{} `json:"args"`
}
```

### 4.2 预编译流程

```go
// CompileSkill - 将配置编译为模板
func CompileSkill(config SkillConfig) (*SkillTemplate, error) {
    tmpl := &SkillTemplate{
        SkillID: config.ID,
    }
    
    // 1. 编译静态效果
    for _, eff := range config.Effects {
        if !hasCondition(eff) {
            tmpl.StaticEffects = append(tmpl.StaticEffects, compileEffect(eff))
        }
    }
    
    // 2. 编译条件效果
    for _, mod := range config.Modifiers {
        tmpl.ConditionalEffects = append(tmpl.ConditionalEffects, ConditionalEffect{
            Condition: compileCondition(mod.Condition),
            Effects:   []Effect{compileEffect(mod.Action)},
        })
        tmpl.RequiredQueries = append(tmpl.RequiredQueries, 
            extractQuery(mod.Condition))
    }
    
    // 3. 如果有Lua，编译字节码
    if config.LuaScript != "" {
        bytecode, err := compileLua(config.LuaScript)
        if err != nil {
            return nil, err
        }
        tmpl.LuaBytecode = bytecode
    }
    
    return tmpl, nil
}
```

### 4.3 运行时执行

```go
func (s *SkillSystem) Execute(w *World, caster EntityID, skillID string, targets []EntityID) {
    tmpl := s.templates[skillID]
    
    // 1. 静态效果
    for _, eff := range tmpl.StaticEffects {
        s.apply(w, eff)
    }
    
    // 2. 批量查询
    ctx := &RuntimeContext{
        Caster:  caster,
        Targets: targets,
        Queries: make(map[QueryType]interface{}),
    }
    for _, q := range tmpl.RequiredQueries {
        ctx.Queries[q] = s.query(w, q, caster, targets)
    }
    
    // 3. 条件效果
    for _, ce := range tmpl.ConditionalEffects {
        if s.eval(ce.Condition, ctx) {
            for _, eff := range ce.Effects {
                s.apply(w, eff)
            }
        }
    }
    
    // 4. Lua (如果需要)
    if tmpl.LuaBytecode != nil {
        effects := s.lua.Execute(tmpl.LuaBytecode, ctx)
        for _, eff := range effects {
            s.apply(w, eff)
        }
    }
}
```

## 5. 性能对比

| 方案 | 单次调用开销 | 适用场景 | 开发难度 |
|------|-------------|----------|----------|
| 原版 Lua (多次回调) | ~500μs | 无 | 中 |
| 简化 Lua (单次调用) | ~50μs | 复杂条件 | 低 |
| JSON + Go | ~10μs | 80%技能 | 极低 |
| 纯 Go | ~5μs | 核心角色 | 中 |

**目标**: 平均 <20μs 单次技能执行

## 6. 实际配置示例

### 菲谢尔 (JSON)

```json
{
  "skill_id": "fischl_skill",
  "name": "夜巡影翼",
  "type": "elemental_skill",
  "cost": {"electro": 3},
  "effects": [
    {
      "type": "damage",
      "target": "active_enemy",
      "params": {"amount": 1, "element": "electro"}
    },
    {
      "type": "summon",
      "target": "self",
      "params": {
        "summon_id": "oz",
        "uses": 2,
        "trigger": "end_phase",
        "trigger_effect": {
          "type": "damage",
          "target": "active_enemy",
          "params": {"amount": 1, "element": "electro"}
        }
      }
    }
  ]
}
```

### 阿蕾奇诺 (Lua)

```lua
-- arlecchino_attack.lua
-- 输入 ctx: {self: {tokens}, target: {tokens, hp}}
-- 输出: 效果列表

function skill(ctx)
    local effects = {}
    local dmg = {amount=2, element="physical"}
    
    -- 元素转换
    if ctx.self.tokens["life_debt"] > 0 then
        dmg.element = "pyro"
    end
    
    -- 消耗敌方token增伤
    local debt = ctx.target.tokens["blood_debt"] or 0
    if debt > 0 then
        local consume = math.min(debt, 3)
        dmg.amount = dmg.amount + consume
        table.insert(effects, {
            type="consume_token",
            target="target",
            params={token="blood_debt", amount=consume}
        })
    end
    
    table.insert(effects, {
        type="damage",
        target="target",
        params=dmg
    })
    
    return effects
end

return skill
```

### 芙宁娜 (Go)

```go
// 在 skill_registry.go 中注册
func init() {
    RegisterNativeSkill("furina_burst", FurinaBurst)
}

func FurinaBurst(w *World, ctx *SkillContext) []Effect {
    // 复杂双形态逻辑
    // ...
}
```

---

## 结论

**推荐方案**: 
1. **JSON 为主** (简单技能，80%)
2. **简化 Lua 为辅** (复杂条件，15%)
3. **纯 Go 保底** (极复杂角色，5%)

**核心优化**:
- 预编译缓存
- 单次 Lua 调用
- 批量查询
- 纯数据输出

这样既保留了 Lua 的灵活性，又满足 RL 的性能需求。
