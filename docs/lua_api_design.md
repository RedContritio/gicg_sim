# Lua API 设计文档

## 设计原则

1. **位置参数** - 只支持位置参数，不支持命名参数
2. **默认值** - 省略后面的参数时自动使用默认值
3. **参数顺序** - 从最重要到最不重要：伤害/效果 > 元素类型 > 目标
4. **命名规范** - 使用小写+下划线，常量使用全大写

---

## 核心 API

### 伤害与治疗

```lua
-- damage(amount, element=PHYSICAL, target=ENEMY_ACTIVE)
-- 造成元素伤害

damage(2)                           -- 2点物理伤害给敌方前台
damage(3, PYRO)                     -- 3点火伤害给敌方前台
damage(1, HYDRO, ENEMY_BACK)        -- 1点水伤害给敌方后台
damage(2, PYRO, SELF)               -- 2点火伤害给自己（自伤）
damage(1, CRYO, ALL_ENEMIES)        -- 1点冰伤害给所有敌人

-- heal(amount, target=SELF)
-- 治疗

heal(2)                             -- 治疗自己2点
heal(3, ALL_ALLIES)                 -- 治疗所有友方3点
```

**参数顺序**: 数量 → 元素 → 目标

**默认值**:
- `element`: `PHYSICAL`
- `target`: `ENEMY_ACTIVE`

---

### 目标常量

| 常量 | 说明 |
|------|------|
| `SELF` | 自己（当前出战角色）|
| `ENEMY_ACTIVE` | 敌方出战角色（前台）|
| `ENEMY_BACK` | 敌方后台角色（第一个后台）|
| `ALL_ENEMIES` | 所有敌方角色 |
| `ALL_ALLIES` | 所有友方角色 |

---

### 元素常量

| 常量 | 说明 |
|------|------|
| `PHYSICAL` | 物理 |
| `PYRO` | 火 |
| `HYDRO` | 水 |
| `CRYO` | 冰 |
| `ELECTRO` | 雷 |
| `ANEMO` | 风 |
| `GEO` | 岩 |
| `DENDRO` | 草 |
| `PIERCING` | 穿透伤害（无视护盾）|

---

### 元素附着

```lua
-- apply_aura(element, duration=2, target=ENEMY_ACTIVE)
-- 给目标附加元素

apply_aura(HYDRO)                   -- 给敌方前台挂水，持续2回合
apply_aura(PYRO, 3)                 -- 给敌方前台挂火，持续3回合
apply_aura(CRYO, 2, SELF)           -- 给自己挂冰，持续2回合

-- has_aura(element, target=ENEMY_ACTIVE)
-- 检查目标是否有某元素附着

has_aura(HYDRO)                     -- 敌方前台有水附着吗？
has_aura(PYRO, SELF)                -- 自己有火附着吗？

-- remove_aura(element, target=ENEMY_ACTIVE)
-- 移除目标的某元素附着

remove_aura(HYDRO)                  -- 移除敌方前台的水附着
```

---

### 计数器

```lua
-- counter(name, default=0, max=999, scope=SCOPE_SKILL)
-- 创建或获取计数器

local combo = counter("combo")                          -- 技能级，默认0，最大999
local debt = counter("blood_debt", 0, 5, SCOPE_CHAR)    -- 角色级，默认0，最大5
local turn = counter("turn", 1, 99, SCOPE_SIDE)         -- 阵营级，默认1，最大99

-- 计数器方法
combo:get()         -- 获取当前值
combo:set(3)        -- 设置为3
combo:add(1)        -- 增加1（原名inc）
combo:sub(1)        -- 减少1（原名dec）
combo:clear()       -- 清零
```

**作用域常量**:
- `SCOPE_SKILL` - 技能级（默认，每次执行技能都是新的）
- `SCOPE_CHAR` - 角色级（当前出战角色共享）
- `SCOPE_SIDE` - 阵营级（整个队伍共享）

---

### Mod 系统

```lua
-- mod.on(event, handler)
-- 注册事件处理器

mod.on("end_phase", function()
    -- 回合结束时的逻辑
    if oz:get() > 0 then
        damage(1, ELECTRO)
        oz:sub(1)
    end
end)

mod.on("damage_calc", function(ctx)
    -- 伤害计算时的逻辑
    -- ctx 包含：amount, element, target, source
    if ctx.element == PYRO and ctx.target:has_aura(HYDRO) then
        ctx.amount = ctx.amount * 2      -- 蒸发翻倍
        ctx.target:remove_aura(HYDRO)    -- 消耗水附着
        print("蒸发！")
    end
end)
```

**事件类型**:
- `"start_phase"` - 回合开始
- `"end_phase"` - 回合结束（当前角色）
- `"round_end"` - 整回合结束（双方）
- `"battle_start"` - 战斗开始
- `"damage_calc"` - 伤害计算（可修改）
- `"before_switch"` - 切换角色前
- `"after_switch"` - 切换角色后

---

### 骰子操作

```lua
-- dice.count(element=ANY)
-- 获取骰子数量

dice.count()                -- 所有骰子数量
dice.count(PYRO)            -- 火骰子数量
dice.count(OMNI)            -- 万能骰数量

-- dice.consume(amount, element=ANY)
-- 消耗骰子

dice.consume(3)             -- 消耗3个任意骰子
dice.consume(2, PYRO)       -- 消耗2个火骰子
dice.consume(1, OMNI)       -- 消耗1个万能骰

-- dice.has(amount, element=ANY)
-- 检查是否有足够骰子

dice.has(3)                 -- 有3个任意骰子吗？
dice.has(2, HYDRO)          -- 有2个水骰子吗？
```

**骰子常量**:
- `PYRO`, `HYDRO`, `CRYO`, `ELECTRO`, `ANEMO`, `GEO`, `DENDRO` - 元素骰
- `OMNI` - 万能骰
- `ANY` - 任意骰（非万能的非元素骰）

---

## 完整示例

### 迪卢克 E 技能

```lua
local combo = counter("e_combo", 0, 3, SCOPE_CHAR)

function on_elemental_skill()
    local count = combo:get()
    
    if count == 2 then
        damage(5, PYRO)     -- 第3段
        combo:clear()
    else
        damage(3, PYRO)     -- 第1、2段
        combo:add(1)
    end
end
```

### 菲谢尔 E 技能（召唤物）

```lua
local oz = counter("oz_duration", 0, 2, SCOPE_CHAR)

-- 回合末触发（如果还没注册过）
if not oz_registered then
    mod.on("end_phase", function()
        if oz:get() <= 0 then return end
        
        damage(1, ELECTRO)
        oz:sub(1)
    end)
    oz_registered = true
end

function on_elemental_skill()
    damage(1, ELECTRO)
    oz:set(2)           -- 奥兹持续2回合
end
```

### 阿蕾奇诺普攻（有血偿勒令）

```lua
local blood_debt = counter("blood_debt", 0, 5, SCOPE_CHAR)

function on_normal_attack()
    local bonus = blood_debt:get()
    damage(2 + bonus, PHYSICAL)
    
    if bonus > 0 then
        blood_debt:clear()
    end
end

function on_elemental_skill()
    damage(2, PYRO)
    blood_debt:set(3)
end
```

### 元素反应（系统级）

```lua
mod.on("damage_calc", function(ctx)
    -- 蒸发：火打水
    if ctx.element == PYRO and ctx.target:has_aura(HYDRO) then
        ctx.amount = ctx.amount * 2
        ctx.target:remove_aura(HYDRO)
        print("💧🔥 蒸发！")
        return
    end
    
    -- 蒸发：水打火
    if ctx.element == HYDRO and ctx.target:has_aura(PYRO) then
        ctx.amount = ctx.amount * 2
        ctx.target:remove_aura(PYRO)
        print("🔥💧 蒸发！")
        return
    end
    
    -- 融化：火打冰
    if ctx.element == PYRO and ctx.target:has_aura(CRYO) then
        ctx.amount = ctx.amount * 2
        ctx.target:remove_aura(CRYO)
        print("❄️🔥 融化！")
        return
    end
    
    -- 融化：冰打火
    if ctx.element == CRYO and ctx.target:has_aura(PYRO) then
        ctx.amount = ctx.amount * 3 // 2
        ctx.target:remove_aura(PYRO)
        print("🔥❄️ 融化！")
        return
    end
    
    -- 没有反应，添加元素附着
    ctx.target:apply_aura(ctx.element, 2)
end)
```

---

## 变更摘要

| 旧 API | 新 API |
|--------|--------|
| `damage(ACTIVE_ENEMY, 2, PYRO)` | `damage(2, PYRO)` |
| `create_counter(0, 5)` | `counter("name", 0, 5)` |
| `counter:inc(1)` | `counter:add(1)` |
| `attach_mod("end_phase", "func")` | `mod.on("end_phase", func)` |
| `has_aura(ACTIVE_ENEMY, HYDRO)` | `has_aura(HYDRO)` 或 `ENEMY_ACTIVE:has_aura(HYDRO)` |
| `get_dice_count(ELECTRO)` | `dice.count(ELECTRO)` |
| `consume_dice({[ELECTRO]=3})` | `dice.consume(3, ELECTRO)` |
