# 基于变量的 Counter 设计

## 核心思想

> **create_counter 返回变量，后续直接操作变量，无需字符串查找。**

```lua
-- 传统方式 (字符串查找)
create_counter("fischl_oz_uses", 0)
set_counter("fischl_oz_uses", 2)  -- 运行时字符串哈希

-- 变量方式 (直接访问)
local oz_uses = create_counter("fischl_oz_uses", 0)
oz_uses:set(2)  -- 直接操作变量
```

## 1. Lua 脚本格式

### 菲谢尔

```lua
-- fischl_e.lua

-- 全局定义区：创建 Counter，返回变量
local oz_uses = create_counter(0, 2)  -- 默认值, 最大值

-- 使用变量定义 Mod
attach_mod({
    event = "end_phase",
    condition = function()
        return oz_uses:get() > 0
    end,
    action = function()
        damage(ACTIVE_ENEMY, 1, ELECTRO)
        oz_uses:dec(1)
    end
})

-- 技能函数：直接操作变量
function on_use()
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:set(2)
end
```

### 迪卢克

```lua
-- diluc_e.lua

local e_combo = create_counter(0, 2)  -- E技能连击计数

attach_mod({
    event = "round_end",
    condition = function() return e_combo:get() > 0 end,
    action = function()
        e_combo:clear()
    end
})

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

local life_debt = create_counter(0, 10)  -- 自身生命之契

-- 被动：给敌方添加血偿勒令
function on_battle_start()
    for _, enemy in ipairs(query(ALL_ENEMIES)) do
        -- 给目标创建 Counter
        local enemy_debt = create_target_counter(enemy, 0, 5)
        enemy_debt:set(3)
    end
end

-- arlecchino_attack.lua

local life_debt = get_counter("life_debt")  -- 引用被动创建的 Counter

attach_mod({
    event = "on_damage_calc",
    condition = function(ctx)
        return life_debt:get() > 0 and ctx.damage.element == PHYSICAL
    end,
    action = function(ctx)
        ctx.damage.element = PYRO
        ctx.damage.amount = ctx.damage.amount + 1
    end
})

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
    
    damage(TARGET, dmg, PHYSICAL)  -- 元素由 Mod 转换
end
```

### 护盾 (迪奥娜)

```lua
-- diona_e.lua

local shield_value = create_counter(0, 5)  -- 护盾值

attach_mod({
    event = "on_damage_receive",
    condition = function(ctx) 
        return shield_value:get() > 0 and ctx.target == SELF
    end,
    action = function(ctx)
        local shield = shield_value:get()
        local block = math.min(shield, ctx.damage.amount)
        
        ctx.damage.amount = ctx.damage.amount - block
        shield_value:dec(block)
    end
})

function on_use()
    damage(ACTIVE_ENEMY, 2, CRYO)
    shield_value:set(2)
end
```

## 2. Counter 对象方法

```lua
-- Counter 对象接口
local counter = create_counter(default, max)

counter:get()       -- 获取当前值
counter:set(n)      -- 设置为 n
counter:inc(n)      -- 增加 n
counter:dec(n)      -- 减少 n
counter:clear()     -- 清零 (set(0))
counter:max()       -- 获取最大值

-- 目标 Counter (对其他角色)
local target_counter = create_target_counter(target_entity, default, max)
-- 同上方法

-- 获取已存在的 Counter
local counter = get_counter("counter_id")  -- 通过ID获取
```

## 3. Go 引擎实现

### Counter 对象绑定

```go
// CounterProxy - Lua 中的 Counter 对象
type CounterProxy struct {
    ID    string
    Side  *Side
    Max   int
}

func (cp *CounterProxy) RegisterMethods(L *lua.State) {
    // 创建 metatable
    L.NewMetaTable("counter_mt")
    
    // 注册方法
    L.PushString("get")
    L.PushGoFunction(func(L *lua.State) int {
        cp := checkCounter(L, 1)
        L.PushInteger(cp.Side.GetCounter(cp.ID))
        return 1
    })
    L.SetTable(-3)
    
    L.PushString("set")
    L.PushGoFunction(func(L *lua.State) int {
        cp := checkCounter(L, 1)
        value := L.ToInteger(2)
        cp.Side.SetCounter(cp.ID, value)
        return 0
    })
    L.SetTable(-3)
    
    L.PushString("inc")
    L.PushGoFunction(func(L *lua.State) int {
        cp := checkCounter(L, 1)
        delta := L.ToInteger(2)
        cp.Side.IncCounter(cp.ID, delta)
        return 0
    })
    L.SetTable(-3)
    
    L.PushString("dec")
    L.PushGoFunction(func(L *lua.State) int {
        cp := checkCounter(L, 1)
        delta := L.ToInteger(2)
        cp.Side.DecCounter(cp.ID, delta)
        return 0
    })
    L.SetTable(-3)
    
    L.PushString("clear")
    L.PushGoFunction(func(L *lua.State) int {
        cp := checkCounter(L, 1)
        cp.Side.SetCounter(cp.ID, 0)
        return 0
    })
    L.SetTable(-3)
}

func checkCounter(L *lua.State, idx int) *CounterProxy {
    cp := (*CounterProxy)(L.CheckUserData(idx, "counter_mt"))
    return cp
}
```

### create_counter 实现

```go
func (l *LuaRuntime) RegisterCreateCounter() {
    L.Register("create_counter", func(L *lua.State) int {
        defaultVal := 0
        maxVal := 999
        
        if L.GetTop() >= 1 {
            defaultVal = L.ToInteger(1)
        }
        if L.GetTop() >= 2 {
            maxVal = L.ToInteger(2)
        }
        
        // 生成唯一 ID
        counterID := l.generateCounterID()
        
        // 创建 Counter 定义
        l.currentSide.CounterDefs[counterID] = CounterDef{
            Default: defaultVal,
            Max:     maxVal,
        }
        
        // 初始化值
        l.currentSide.Counters[counterID] = defaultVal
        
        // 创建 CounterProxy 并压入 Lua
        proxy := &CounterProxy{
            ID:   counterID,
            Side: l.currentSide,
            Max:  maxVal,
        }
        
        L.PushUserData(proxy)
        L.GetMetaTable("counter_mt")
        L.SetMetaTable(-2)
        
        return 1  // 返回 Counter 对象
    })
}
```

### 预扫描提取 Counter ID

```go
// PreScanner 现在需要跟踪变量名到 ID 的映射
type PreScanner struct {
    counters map[string]*CounterDef  // ID -> Def
    varToID  map[string]string       // 变量名 -> ID
    nextID   int
}

func (s *PreScanner) Scan(luaCode string) error {
    L := lua.NewState()
    defer L.Close()
    
    // 创建假的 create_counter，只提取信息
    L.Register("create_counter", func(L *lua.State) int {
        // 获取变量名（从赋值语句）
        // Lua 中 local x = create_counter(...)
        // 我们需要解析源码获取变量名
        
        id := fmt.Sprintf("counter_%d", s.nextID)
        s.nextID++
        
        def := 0
        max := 999
        if L.GetTop() >= 1 {
            def = L.ToInteger(1)
        }
        if L.GetTop() >= 2 {
            max = L.ToInteger(2)
        }
        
        s.counters[id] = &CounterDef{
            ID:      id,
            Default: def,
            Max:     max,
        }
        
        // 压入假的 Counter 对象
        L.PushUserData(&FakeCounter{ID: id})
        return 1
    })
    
    // 执行脚本提取定义
    if err := L.DoString(luaCode); err != nil {
        return err
    }
    
    return nil
}
```

## 4. 优势对比

| 方式 | 代码清晰度 | 性能 | 类型安全 |
|------|-----------|------|----------|
| 字符串 `"counter_name"` | 差 | 慢(哈希) | 无 |
| **变量 `oz_uses`** | **好** | **快(直接访问)** | **有** |

## 5. 完整示例对比

### 字符串方式

```lua
function on_use()
    local combo = get_counter("diluc_e_combo")
    if combo >= 2 then
        damage(ACTIVE_ENEMY, 5, PYRO)
        clear_counter("diluc_e_combo")
    else
        damage(ACTIVE_ENEMY, 3, PYRO)
        inc_counter("diluc_e_combo", 1)
    end
end
```

### 变量方式

```lua
local e_combo = create_counter(0, 2)

function on_use()
    if e_combo:get() >= 2 then
        damage(ACTIVE_ENEMY, 5, PYRO)
        e_combo:clear()
    else
        damage(ACTIVE_ENEMY, 3, PYRO)
        e_combo:inc(1)
    end
end
```

**更清晰，更 Lua 风格。**
