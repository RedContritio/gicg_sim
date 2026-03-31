# Lua API 设计文档 V2

## 计数器系统

### create_counter(name, initial, scope)

创建或获取计数器。

**参数**:
- `name`: string - 计数器名称
- `initial`: number - 初始值
- `scope`: string - 作用域，可选值：
  - `"SKILL"` - 技能级，每个脚本独立
  - `"CHARACTER"` - 角色级，同一角色共享
  - `"SIDE"` - 阵营级，同一阵营共享

**返回值**: Counter 对象

**重复创建规则**:
- 如果在同一 scope 范围内已存在同名计数器：
  - 校验 `initial` 是否一致，不一致则报错
  - 一致则返回已存在的计数器实例

**示例**:
```lua
-- 技能级：每次执行技能都是新的计数器
local combo = create_counter("combo", 0, "SKILL")

-- 角色级：同一角色的不同技能共享
local debt = create_counter("blood_debt", 0, "CHARACTER")

-- 阵营级：整个队伍共享
local turn = create_counter("turn_count", 1, "SIDE")
```

### Counter 方法

| 方法 | 说明 |
|------|------|
| `counter:get()` | 获取当前值 |
| `counter:set(value)` | 设置值 |
| `counter:add(n)` | 增加 n |
| `counter:sub(n)` | 减少 n |
| `counter:clear()` | 重置为初始值 |

---

## 伤害与治疗

### damage(amount, element, target)

**参数**:
- `amount`: number - 伤害值（必填）
- `element`: Element - 元素类型，默认 `PHYSICAL`
- `target`: Target - 目标，默认 `ENEMY_ACTIVE`

**示例**:
```lua
damage(2)                       -- 2点物理伤害，敌方前台
damage(3, PYRO)                 -- 3点火伤害，敌方前台
damage(1, HYDRO, ENEMY_BACK)    -- 1点水伤害，敌方后台
damage(2, PYRO, SELF)           -- 2点火伤害，自己
```

### heal(amount, target)

**参数**:
- `amount`: number - 治疗量（必填）
- `target`: Target - 目标，默认 `SELF`

**示例**:
```lua
heal(2)                         -- 治疗自己2点
heal(3, ALL_ALLIES)             -- 治疗所有友方3点
```

---

## 元素附着

### apply_aura(element, duration, target)

**参数**:
- `element`: Element - 元素类型（必填）
- `duration`: number - 持续回合，默认 `2`
- `target`: Target - 目标，默认 `ENEMY_ACTIVE`

### has_aura(element, target)

**参数**:
- `element`: Element - 元素类型（必填）
- `target`: Target - 目标，默认 `ENEMY_ACTIVE`

**返回值**: boolean

### remove_aura(element, target)

**参数**:
- `element`: Element - 元素类型（必填）
- `target`: Target - 目标，默认 `ENEMY_ACTIVE`

**示例**:
```lua
apply_aura(HYDRO)               -- 给敌方前台挂水，2回合
apply_aura(PYRO, 3)             -- 给敌方前台挂火，3回合
apply_aura(CRYO, 2, SELF)       -- 给自己挂冰，2回合

if has_aura(HYDRO) then         -- 敌方前台有水附着吗？
    remove_aura(HYDRO)          -- 移除水附着
end
```

---

## Mod 系统

### attach_mod(event, func_name)

注册事件处理器。

**参数**:
- `event`: string - 事件名称
- `func_name`: string - 处理函数名（全局函数）

**事件类型**:
- `"start_phase"` - 回合开始
- `"end_phase"` - 回合结束
- `"round_end"` - 整回合结束（双方）
- `"battle_start"` - 战斗开始
- `"damage_calc"` - 伤害计算（可修改）
- `"before_switch"` - 切换角色前
- `"after_switch"` - 切换角色后

**damage_calc 专用 API**:
- `get_damage_info()` - 获取当前伤害信息表
- `set_damage_amount(amount)` - 设置伤害值

**伤害信息表结构**:
```lua
{
    amount = 3,         -- 原始伤害
    element = PYRO,     -- 伤害元素
    target_id = "diluc",    -- 目标角色ID
    source_id = "xiangling" -- 来源角色ID
}
```

**示例**:
```lua
-- 回合末触发
function on_end_phase()
    if oz:get() > 0 then
        damage(1, ELECTRO)
        oz:sub(1)
    end
end
attach_mod("end_phase", "on_end_phase")

-- 伤害计算时触发（元素反应）
function on_damage_calc()
    local info = get_damage_info()
    
    if info.element == PYRO and has_aura(HYDRO, info.target_id) then
        set_damage_amount(info.amount * 2)
        remove_aura(HYDRO, info.target_id)
        print("蒸发！")
    end
end
attach_mod("damage_calc", "on_damage_calc")
```

---

## 骰子操作

### get_dice_count(element)

**参数**:
- `element`: Element - 元素类型，默认 `ANY`

**返回值**: number

### consume_dice(amount, element)

**参数**:
- `amount`: number - 消耗数量（必填）
- `element`: Element - 元素类型，默认 `ANY`

**返回值**: boolean - 是否成功

### can_afford_dice(amount, element)

**参数**:
- `amount`: number - 所需数量（必填）
- `element`: Element - 元素类型，默认 `ANY`

**返回值**: boolean

**示例**:
```lua
get_dice_count()            -- 所有骰子数量
get_dice_count(PYRO)        -- 火骰子数量
get_dice_count(OMNI)        -- 万能骰数量

consume_dice(3)             -- 消耗3个任意骰子
consume_dice(2, PYRO)       -- 消耗2个火骰子

if can_afford_dice(3, HYDRO) then
    -- 有足够的水骰子
end
```

---

## 常量

### 目标
- `SELF` - 自己
- `ENEMY_ACTIVE` - 敌方出战角色
- `ENEMY_BACK` - 敌方后台角色
- `ALL_ENEMIES` - 所有敌人
- `ALL_ALLIES` - 所有友方

### 元素
- `PHYSICAL` - 物理
- `PYRO` - 火
- `HYDRO` - 水
- `CRYO` - 冰
- `ELECTRO` - 雷
- `ANEMO` - 风
- `GEO` - 岩
- `DENDRO` - 草
- `PIERCING` - 穿透伤害

### 骰子
- `PYRO`, `HYDRO`, `CRYO`, `ELECTRO`, `ANEMO`, `GEO`, `DENDRO` - 元素骰
- `OMNI` - 万能骰
- `ANY` - 任意骰

---

## 完整示例

### 迪卢克 E 技能
```lua
local combo = create_counter("e_combo", 0, "CHARACTER")

function on_elemental_skill()
    local count = combo:get()
    
    if count == 2 then
        damage(5, PYRO)
        combo:clear()
    else
        damage(3, PYRO)
        combo:add(1)
    end
end
```

### 菲谢尔 E 技能（召唤物）
```lua
local oz = create_counter("oz_duration", 0, "CHARACTER")

function on_end_phase()
    if oz:get() <= 0 then return end
    
    damage(1, ELECTRO)
    oz:sub(1)
end
attach_mod("end_phase", "on_end_phase")

function on_elemental_skill()
    damage(1, ELECTRO)
    oz:set(2)
end
```

### 阿蕾奇诺普攻
```lua
local blood_debt = create_counter("blood_debt", 0, "CHARACTER")

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

### 系统级元素反应
```lua
function on_damage_calc()
    local info = get_damage_info()
    
    -- 蒸发：火打水
    if info.element == PYRO and has_aura(HYDRO, info.target_id) then
        set_damage_amount(info.amount * 2)
        remove_aura(HYDRO, info.target_id)
        print("💧🔥 蒸发！")
        return
    end
    
    -- 蒸发：水打火
    if info.element == HYDRO and has_aura(PYRO, info.target_id) then
        set_damage_amount(info.amount * 2)
        remove_aura(PYRO, info.target_id)
        print("🔥💧 蒸发！")
        return
    end
    
    -- 融化：火打冰
    if info.element == PYRO and has_aura(CRYO, info.target_id) then
        set_damage_amount(info.amount * 2)
        remove_aura(CRYO, info.target_id)
        print("❄️🔥 融化！")
        return
    end
    
    -- 融化：冰打火
    if info.element == CRYO and has_aura(PYRO, info.target_id) then
        set_damage_amount(info.amount * 3 // 2)
        remove_aura(PYRO, info.target_id)
        print("🔥❄️ 融化！")
        return
    end
    
    -- 超导：冰+雷
    if (info.element == CRYO and has_aura(ELECTRO, info.target_id)) or
       (info.element == ELECTRO and has_aura(CRYO, info.target_id)) then
        set_damage_amount(info.amount + 1)
        remove_aura(CRYO, info.target_id)
        remove_aura(ELECTRO, info.target_id)
        print("⚡❄️ 超导！")
        return
    end
    
    -- 超载：火+雷
    if (info.element == PYRO and has_aura(ELECTRO, info.target_id)) or
       (info.element == ELECTRO and has_aura(PYRO, info.target_id)) then
        set_damage_amount(info.amount + 2)
        remove_aura(PYRO, info.target_id)
        remove_aura(ELECTRO, info.target_id)
        print("⚡🔥 超载！")
        return
    end
    
    -- 感电：水+雷
    if (info.element == HYDRO and has_aura(ELECTRO, info.target_id)) or
       (info.element == ELECTRO and has_aura(HYDRO, info.target_id)) then
        set_damage_amount(info.amount + 1)
        remove_aura(HYDRO, info.target_id)
        remove_aura(ELECTRO, info.target_id)
        print("⚡💧 感电！")
        return
    end
    
    -- 冻结：水+冰
    if (info.element == HYDRO and has_aura(CRYO, info.target_id)) or
       (info.element == CRYO and has_aura(HYDRO, info.target_id)) then
        remove_aura(HYDRO, info.target_id)
        remove_aura(CRYO, info.target_id)
        apply_aura(CRYO, 1, info.target_id) -- 冻元素
        print("❄️💧 冻结！")
        return
    end
    
    -- 无反应，添加元素附着
    apply_aura(info.element, 2, info.target_id)
end

attach_mod("damage_calc", "on_damage_calc")
```
