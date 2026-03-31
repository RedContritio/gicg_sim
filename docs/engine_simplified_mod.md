# 简化 Mod 设计

## 核心简化

> **Mod 只有 Event + Function，判断逻辑写在函数里。**

```lua
-- 之前
attach_mod({
    event = "end_phase",
    condition = function() return oz_uses:get() > 0 end,
    action = function()
        damage(ACTIVE_ENEMY, 1, ELECTRO)
        oz_uses:dec(1)
    end
})

-- 现在
attach_mod("end_phase", function()
    if oz_uses:get() > 0 then
        damage(ACTIVE_ENEMY, 1, ELECTRO)
        oz_uses:dec(1)
    end
end)
```

## 1. 新 Lua 格式

### 菲谢尔

```lua
-- fischl_e.lua

-- 创建 Counter
local oz_uses = create_counter(0, 2)

-- 附加 Mod：事件 + 处理函数
attach_mod("end_phase", function()
    if oz_uses:get() <= 0 then
        return  -- 条件不满足直接返回
    end
    
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:dec(1)
end)

function on_use()
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:set(2)
end
```

### 迪卢克

```lua
-- diluc_e.lua

local e_combo = create_counter(0, 2)

-- 回合结束重置
attach_mod("round_end", function()
    if e_combo:get() > 0 then
        e_combo:clear()
    end
end)

function on_use()
    local combo = e_combo:get()
    
    if combo >= 2 then
        damage(ACTIVE_ENEMY, 5, PYRO)
        e_combo:clear()
    else
        damage(ACTIVE_ENEMY, 3, PYRO)
        e_combo:inc(1)
    end
end
```

### 阿蕾奇诺

```lua
-- arlecchino_passive.lua

local life_debt = create_counter(0, 10)

function on_battle_start()
    for _, enemy in ipairs(query(ALL_ENEMIES)) do
        local debt = create_target_counter(enemy, 0, 5)
        debt:set(3)
    end
end

-- arlecchino_attack.lua

local life_debt = get_counter("life_debt")

-- 元素转换 Mod
attach_mod("on_damage_calc", function(ctx)
    -- 自己有生命之契，且伤害是物理
    if life_debt:get() <= 0 then
        return
    end
    if ctx.damage.element ~= PHYSICAL then
        return
    end
    
    -- 转为火元素，伤害+1
    ctx.damage.element = PYRO
    ctx.damage.amount = ctx.damage.amount + 1
end)

function on_use()
    local dmg = 2
    
    -- 消耗敌方血偿勒令
    local enemy_debt = get_target_counter(TARGET, "blood_debt")
    local debt = enemy_debt:get()
    if debt > 0 then
        local consume = math.min(debt, 3)
        dmg = dmg + consume
        enemy_debt:dec(consume)
    end
    
    damage(TARGET, dmg, PHYSICAL)
end
```

### 护盾 (迪奥娜)

```lua
-- diona_e.lua

local shield = create_counter(0, 5)

-- 伤害拦截 Mod
attach_mod("on_damage_receive", function(ctx)
    -- 检查是否是自己受到伤害
    if ctx.target ~= SELF then
        return
    end
    
    local shield_val = shield:get()
    if shield_val <= 0 then
        return
    end
    
    -- 计算抵挡
    local block = math.min(shield_val, ctx.damage.amount)
    ctx.damage.amount = ctx.damage.amount - block
    shield:dec(block)
end)

function on_use()
    damage(ACTIVE_ENEMY, 2, CRYO)
    shield:set(2)
end
```

## 2. attach_mod 简化 API

```lua
-- 只有两个参数：事件类型、处理函数
attach_mod(event, handler)

-- 事件类型列表
"start_phase"          -- 阶段开始
"end_phase"            -- 阶段结束
"round_end"            -- 回合结束
"on_damage_calc"       -- 伤害计算时
"on_damage_receive"    -- 受到伤害时
"on_battle_start"      -- 战斗开始
"on_skill_use"         -- 技能使用时
"before_switch"        -- 切换角色前
"after_switch"         -- 切换角色后
```

## 3. Go 引擎实现

```go
// Mod 定义
type Mod struct {
    ID       string
    Source   string      // 来源卡牌
    Event    string      // 事件类型
    Handler  *lua.FunctionRef  // Lua 函数引用
}

// attach_mod 注册
func (l *LuaRuntime) RegisterAttachMod() {
    L.Register("attach_mod", func(L *lua.State) int {
        event := L.ToString(1)
        
        // 保存函数引用
        handlerRef := L.Ref(lua.REGISTRYINDEX)
        
        mod := &Mod{
            ID:      l.generateModID(),
            Source:  l.currentCard,
            Event:   event,
            Handler: handlerRef,
        }
        
        l.currentSide.Mods = append(l.currentSide.Mods, mod)
        
        return 0
    })
}

// 事件触发
func (w *World) TriggerEvent(event string, ctx *EventContext) {
    for _, side := range w.Sides {
        for _, mod := range side.Mods {
            if mod.Event != event {
                continue
            }
            
            // 调用 Lua 函数
            w.lua.CallModHandler(mod.Handler, ctx)
        }
    }
}
```

## 4. API 最终版 (14个)

```lua
-- Counter 操作 (4个)
local c = create_counter(default, max)
c:get()
c:set(n)
c:inc(n)
c:dec(n)

-- 目标 Counter (3个)
local tc = create_target_counter(target, default, max)
get_target_counter(target)

-- Mod (1个)
attach_mod(event, handler)

-- 基础效果 (4个)
damage(target, amount, element)
heal(target, amount)
draw_cards(n)
switch_to(target)

-- 查询 (2个)
query(target_type)
get_hp(target)

-- 总共 14 个 API
```

## 5. Token 词汇表 (50个)

```python
VOCAB = {
    # Lua (8个)
    'function', 'end', 'if', 'then', 'else', 'for', 'in', 'return', 'local',
    
    # API (14个)
    'create_counter', 'get', 'set', 'inc', 'dec',
    'create_target_counter', 'get_target_counter',
    'attach_mod',
    'damage', 'heal', 'draw_cards', 'switch_to',
    'query', 'get_hp',
    
    # 目标 (7个)
    'SELF', 'TARGET', 'ACTIVE_ENEMY', 'ALL_ENEMIES', 'BACK_ENEMIES', 'ALL_ALLIES',
    
    # 元素 (9个)
    'PYRO', 'HYDRO', 'CRYO', 'ELECTRO', 'ANEMO', 'GEO', 'DENDRO', 'PHYSICAL', 'PIERCING',
    
    # 事件 (10个)
    'start_phase', 'end_phase', 'round_end',
    'on_damage_calc', 'on_damage_receive', 'on_battle_start',
    'on_skill_use', 'before_switch', 'after_switch',
    
    # 符号
    '(', ')', '{', '}', ',', '.', '=', '==', '<', '>', '<=', '>=',
    
    # 特殊
    '<PAD>', '<UNK>', '<NUMBER>', '<STRING>',
}

# 约 50 个 token
```

## 6. 对比总结

| 版本 | 复杂度 | API数 | Token数 |
|------|--------|-------|---------|
| 最初 ECS | 高 | 30+ | - |
| 第一版 Mod | 中 | 20 | 80 |
| Counter+Mod分离 | 低 | 17 | 60 |
| **变量+简化Mod** | **极简** | **14** | **50** |

## 7. 完整菲谢尔代码

```lua
-- fischl_e.lua (约 15 行)
local oz_uses = create_counter(0, 2)

attach_mod("end_phase", function()
    if oz_uses:get() <= 0 then return end
    
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:dec(1)
end)

function on_use()
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:set(2)
end
```

---

**最终设计**: 极简 API，清晰逻辑，约 50 个 token。
