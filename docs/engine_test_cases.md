# 引擎架构测试案例

## 测试案例 1: 菲谢尔（简单召唤物）

### 机制验证
- [x] 技能执行产生伤害
- [x] 召唤物创建
- [x] 结束阶段触发
- [x] 可用次数递减

### 测试场景
```
初始: 菲谢尔出战，敌方角色A出战

动作1: 菲谢尔使用元素战技
- 期望: 
  - 敌方A受到1点雷伤
  - 我方场上出现"奥兹"(可用次数2)

阶段: 进入结束阶段
- 期望:
  - 敌方A受到1点雷伤(奥兹触发)
  - 奥兹可用次数变为1

动作2: 菲谢尔使用其他技能
阶段: 进入结束阶段
- 期望:
  - 敌方A受到1点雷伤(奥兹触发)
  - 奥兹可用次数变为0，消失
```

### Lua 脚本
```lua
function elemental_skill(ctx)
    return {
        {type="damage", target=ctx.targets[1], amount=1, element="electro"},
        {type="summon", summon_id="oz", uses=2, trigger="end_phase", 
         effect={type="damage", amount=1, element="electro"}}
    }
end
```

---

## 测试案例 2: 阿蕾奇诺（层数系统 + 伤害转换）

### 机制验证
- [x] Token 层数叠加/消耗
- [x] 战斗开始被动触发
- [x] 伤害类型动态转换
- [x] 治疗过滤（阻止非特定来源治疗）
- [x] 敌方场上状态（血偿勒令）

### 测试场景
```
初始: 战斗开始

被动触发:
- 期望: 所有敌方角色获得3层"血偿勒令"

回合1 - 阿蕾奇诺普攻敌方A(有3层血偿勒令):
- 期望:
  - 消耗敌方A的3层血偿勒令
  - 造成2+3=5点物理伤害

回合2 - 阿蕾奇诺给自己加2层生命之契:
- 期望: 阿蕾奇诺获得2层生命之契

回合3 - 阿蕾奇诺普攻敌方B(无血偿勒令):
- 期望:
  - 由于自己有生命之契，伤害转为火元素
  - 造成2点火元素伤害

回合4 - 阿蕾奇诺使用元素爆发:
- 期望:
  - 造成4点火元素伤害
  - 消耗2层生命之契，治疗2点

回合5 - 其他角色试图治疗阿蕾奇诺:
- 期望: 治疗被阻止（被动过滤）
```

### Lua 脚本
```lua
-- 被动: 战斗开始时
function passive_battle_start(ctx)
    local effects = {}
    for _, enemy in ipairs(ctx.api:QueryTargets("all_enemies")) do
        table.insert(effects, {
            type = "add_token",
            target = enemy,
            token_id = "blood_debt",
            stacks = 3
        })
    end
    return effects
end

-- 普攻
function normal_attack(ctx)
    local target = ctx.targets[1]
    local damage = 2
    
    -- 消耗敌方血偿勒令
    local debt = ctx.api:ConsumeToken(target, "blood_debt", 3)
    damage = damage + debt
    
    -- 检查自己的生命之契进行元素转换
    local element = "physical"
    if ctx.api:GetTokenStacks(ctx.caster, "life_debt") > 0 then
        element = "pyro"
    end
    
    return {{type="damage", target=target, amount=damage, element=element}}
end

-- 被动: 治疗过滤
function on_heal(ctx, event)
    if event.source ~= ctx.caster then
        return {type="prevent"}  -- 阻止治疗
    end
end
```

---

## 测试案例 3: 甘雨（多目标 + 穿透伤害）

### 机制验证
- [x] 多目标伤害
- [x] 穿透伤害（无视护盾）
- [x] 召唤物+范围伤害

### 测试场景
```
初始: 敌方有3个角色(A出战，B和C后台)

动作: 甘雨使用元素爆发
- 期望:
  - 敌方A受到2点冰元素伤害
  - 敌方B受到1点穿透伤害
  - 敌方C受到1点穿透伤害
  - 召唤"冰灵珠"(结束阶段触发)

结束阶段:
- 期望:
  - 敌方A受到2点冰元素伤害(冰灵珠触发)
```

### Lua 脚本
```lua
function elemental_burst(ctx)
    local effects = {}
    
    -- 主战角色伤害
    table.insert(effects, {
        type = "damage",
        target = ctx.targets[1],
        amount = 2,
        element = "cryo"
    })
    
    -- 后台穿透伤害
    for _, enemy in ipairs(ctx.api:QueryTargets("back_enemies")) do
        table.insert(effects, {
            type = "damage",
            target = enemy,
            amount = 1,
            element = "piercing"  -- 穿透
        })
    end
    
    -- 召唤
    table.insert(effects, {
        type = "summon",
        summon_id = "ice_lotus",
        uses = 2,
        trigger = "end_phase"
    })
    
    return effects
end
```

---

## 测试案例 4: 芙宁娜（双形态 + 全局影响）

### 机制验证
- [x] 角色双形态切换
- [x] 全局光环效果
- [x] 基于队伍配置的效果

### 测试场景
```
芙宁娜有"荒"和"芒"两种形态

荒形态特性:
- 元素战技召唤"沙龙成员"(召唤物)
- 全队角色生命值高于50%时，伤害+1

芒形态特性:
- 元素战技治疗全队
- 受到治疗的角色下次伤害+1

切换机制:
- 使用元素爆发时切换形态

测试流程:
1. 芙宁娜(荒)使用战技 -> 召唤沙龙成员
2. 检查: 角色HP>50%，伤害+1效果激活
3. 芙宁娜使用爆发 -> 切换为芒形态
4. 芙宁娜(芒)使用战技 -> 治疗全队
5. 检查: 被治疗角色有"下次伤害+1"token
```

### Lua 脚本
```lua
-- 荒形态战技
function elemental_skill_ousia(ctx)
    return {
        {type="summon", summon_id="salon_members", uses=3},
        {type="apply_aura", aura="ousia_damage_bonus"}  -- 全局光环
    }
end

-- 芒形态战技
function elemental_skill_pneuma(ctx)
    local effects = {}
    for _, ally in ipairs(ctx.api:QueryTargets("all_allies")) do
        table.insert(effects, {
            type = "heal",
            target = ally,
            amount = 2
        })
        table.insert(effects, {
            type = "add_token",
            target = ally,
            token_id = "next_damage_plus_1",
            stacks = 1
        })
    end
    return effects
end

-- 被动: 荒形态伤害加成检查
function on_damage_calc(ctx, dmg)
    if ctx.api:HasAura("ousia_damage_bonus") then
        local hp_percent = ctx.api:GetHPPercent(dmg.source)
        if hp_percent > 0.5 then
            dmg.amount = dmg.amount + 1
        end
    end
    return dmg
end
```

---

## 测试案例 5: 莫娜（被动触发 + 快速行动）

### 机制验证
- [x] 被动技能触发
- [x] 每回合限制（1次）
- [x] 行动类型修改（战斗行动→快速行动）

### 测试场景
```
莫娜被动: 每回合1次，切换角色视为"快速行动"

测试1:
- 回合内第一次切换 -> 应该是快速行动（不结束回合）
- 回合内第二次切换 -> 应该是普通战斗行动（结束回合）

测试2:
- 新回合开始 -> 计数器重置
- 第一次切换 -> 又是快速行动
```

### Lua 脚本
```lua
-- 被动: 切换角色时
function on_character_switch(ctx, event)
    -- 检查是否已使用过
    local used = ctx.api:GetTokenStacks(ctx.caster, "switch_used")
    if used == 0 then
        -- 标记已使用
        ctx.api:AddToken(ctx.caster, "switch_used", 1)
        -- 修改行动类型为快速
        return {type="modify_action", new_type="fast_action"}
    end
    return nil
end

-- 回合开始时重置
function on_turn_start(ctx)
    ctx.api:ConsumeToken(ctx.caster, "switch_used", 999)
    return {}
end
```

---

## 测试案例 6: 复杂交互测试（多角色配合）

### 场景设定
```
我方: 菲谢尔 + 阿蕾奇诺 + 甘雨
敌方: 3个角色

回合流程:
1. 菲谢尔出战，使用战技召唤奥兹
2. 切换阿蕾奇诺(快速行动，莫娜被动)
3. 阿蕾奇诺普攻，消耗敌方血偿勒令
4. 结束阶段:
   - 奥兹触发，造成雷伤
   - 检查元素反应

验证:
- 召唤物正确触发
- Token层数正确消耗
- 被动正确触发和限制
- 元素反应正确计算
```

---

## 验证清单

| 机制 | 案例1 | 案例2 | 案例3 | 案例4 | 案例5 |
|------|-------|-------|-------|-------|-------|
| 基础伤害 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 召唤物 | ✓ | | ✓ | ✓ | |
| Token层数 | | ✓ | | ✓ | ✓ |
| 被动触发 | | ✓ | | ✓ | ✓ |
| 伤害转换 | | ✓ | | | |
| 多目标 | | | ✓ | ✓ | |
| 穿透伤害 | | | ✓ | | |
| 治疗过滤 | | ✓ | | | |
| 快速行动 | | | | | ✓ |
| 全局光环 | | | | ✓ | |
| 形态切换 | | | | ✓ | |

---

## 架构覆盖度评估

### ECS 组件使用

| 组件 | 使用场景 |
|------|----------|
| HPComponent | 所有角色 |
| EnergyComponent | 有爆发的角色 |
| ElementComponent | 所有角色（附着） |
| SkillComponent | 所有角色 |
| SummonComponent | 菲谢尔、甘雨、芙宁娜 |
| TokenComponent | 阿蕾奇诺、芙宁娜、莫娜 |
| PassiveComponent | 阿蕾奇诺、莫娜、芙宁娜 |
| DamageModComponent | 阿蕾奇诺（元素转换） |

### 系统交互

```
SkillSystem -> LuaRuntime -> EffectList
    |
    v
SummonSystem (创建召唤物)
    |
    v
TokenSystem (添加/消耗层数)
    |
    v
DamageSystem -> ElementSystem (元素反应)
    |
    v
PhaseSystem (结束阶段触发)
```

所有测试案例均可通过此架构实现。
