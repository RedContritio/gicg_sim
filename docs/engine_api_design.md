# 固定 API 设计

## 核心思想

> **所有效果都通过固定 API 表达，减少 Token 种类。**

```lua
-- 不要这样
{type = "damage", target = "active_enemy", amount = 2}

-- 而是这样  
damage(ACTIVE_ENEMY, 2, PYRO)
```

## 1. API 列表 (共 20 个)

### 基础效果 (8个)

```go
// damage(target, amount, element)
// 造成元素伤害
damage(ACTIVE_ENEMY, 2, PYRO)           // 2点火伤
damage(ALL_ENEMIES, 1, PIERCING)        // 全体1点穿透

// heal(target, amount)
// 治疗
heal(SELF, 4)
heal(ALL_ALLIES, 2)

// add_energy(target, amount)
// 增加能量
add_energy(SELF, 1)

// attach_element(target, element)
// 附着元素
attach_element(ACTIVE_ENEMY, PYRO)

// draw_cards(n)
// 抽牌
draw_cards(2)

// switch_to(target)
// 切换角色
switch_to(NEXT_CHAR)
```

### Counter 操作 (6个)

```go
// set_counter(name, value)
// 设置计数器
set_counter("fischl_oz_uses", 2)

// inc_counter(name, delta)
// 增加计数器
inc_counter("diluc_e_combo", 1)

// dec_counter(name, delta)
// 减少计数器
dec_counter("fischl_oz_uses", 1)

// clear_counter(name)
// 清空计数器
clear_counter("diluc_e_combo")

// get_counter(name) -> int
// 获取计数器值
if get_counter("diluc_e_combo") >= 2 then ...

// get_target_counter(target, name) -> int
// 获取目标计数器
local debt = get_target_counter(TARGET, "blood_debt")
```

### Mod 操作 (4个)

```go
// add_mod(mod_id)
// 添加 Mod
add_mod("fischl_oz_trigger")

// remove_mod(mod_id)
// 移除 Mod
remove_mod("fischl_oz_trigger")

// has_mod(mod_id) -> bool
// 检查是否有 Mod
if has_mod("pyro_infusion") then ...

// query_mod(mod_id) -> table
// 查询 Mod 信息
```

### 查询 (2个)

```go
// query_target(type) -> entity
// 查询目标
query_target(ACTIVE_ENEMY)   // 敌方出战
query_target(ALL_ALLIES)     // 所有友方

// get_hp(target) -> int
// 获取生命值
if get_hp(SELF) < 5 then ...
```

## 2. 完整角色示例

### 菲谢尔

```lua
-- skill_fischl_e.lua
function on_use()
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    set_counter("fischl_oz_uses", 2)
    add_mod("fischl_oz_trigger")
end

-- mod_fischl_oz.lua (配置，非脚本)
-- event: end_phase
-- condition: get_counter("fischl_oz_uses") > 0
-- action: |
--   damage(ACTIVE_ENEMY, 1, ELECTRO)
--   dec_counter("fischl_oz_uses", 1)
--   if get_counter("fischl_oz_uses") == 0 then
--       remove_mod("fischl_oz_trigger")
--   end
```

### 迪卢克

```lua
-- skill_diluc_e.lua
function on_use()
    local combo = get_counter("diluc_e_combo")
    
    if combo >= 2 then
        damage(ACTIVE_ENEMY, 5, PYRO)
        clear_counter("diluc_e_combo")
        remove_mod("diluc_e_reset")  -- 移除清理Mod
    else
        damage(ACTIVE_ENEMY, 3, PYRO)
        inc_counter("diluc_e_combo", 1)
        if combo == 0 then
            add_mod("diluc_e_reset")  -- 添加回合结束清理
        end
    end
end

-- mod_diluc_e_reset.lua (配置)
-- event: round_end
-- action: clear_counter("diluc_e_combo")
```

### 阿蕾奇诺

```lua
-- passive_arlecchino.lua (战斗开始时)
function on_battle_start()
    for _, enemy in ipairs(query_target(ALL_ENEMIES)) do
        set_target_counter(enemy, "blood_debt", 3)
    end
end

-- skill_arlecchino_attack.lua
function on_use()
    local dmg = 2
    local element = PHYSICAL
    
    -- 自身有生命之契时转火伤
    if get_counter("arlecchino_life_debt") > 0 then
        element = PYRO
    end
    
    -- 消耗敌方血偿勒令增伤
    local debt = get_target_counter(TARGET, "blood_debt")
    if debt > 0 then
        local consume = math.min(debt, 3)
        dmg = dmg + consume
        dec_target_counter(TARGET, "blood_debt", consume)
    end
    
    damage(TARGET, dmg, element)
end
```

## 3. Token 词汇表 (精简版)

```python
VOCAB = {
    # Lua 关键字 (10个)
    'function', 'end', 'if', 'then', 'else', 'elseif', 'for', 'in', 'do', 'local', 'return',
    
    # API 函数 (20个)
    'damage', 'heal', 'add_energy', 'attach_element', 'draw_cards', 'switch_to',
    'set_counter', 'inc_counter', 'dec_counter', 'clear_counter', 
    'get_counter', 'get_target_counter', 'set_target_counter', 'dec_target_counter',
    'add_mod', 'remove_mod', 'has_mod',
    'query_target', 'get_hp',
    'ipairs',  -- Lua标准库
    
    # 目标常量 (10个)
    'SELF', 'TARGET', 'ACTIVE_ENEMY', 'ALL_ENEMIES', 'BACK_ENEMIES',
    'ALL_ALLIES', 'NEXT_CHAR', 'PREV_CHAR', 'CHAR_0', 'CHAR_1', 'CHAR_2',
    
    # 元素常量 (9个)
    'PYRO', 'HYDRO', 'CRYO', 'ELECTRO', 'ANEMO', 'GEO', 'DENDRO', 'PHYSICAL', 'PIERCING',
    
    # 数值 (离散化)
    'N_0', 'N_1', 'N_2', 'N_3', 'N_4', 'N_5', 'N_6', 'N_7', 'N_8', 'N_9',
    'N_10', 'N_10+',
    
    # 运算符
    '+', '-', '*', '/', '=', '==', '~=', '<', '>', '<=', '>=',
    
    # 符号
    '(', ')', '{', '}', ',', '.', '[', ']',
    
    # 特殊
    '<PAD>', '<UNK>', '<STR>',
}

# 总共约 80 个 token
```

## 4. 技能编码示例

```lua
-- 代码
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

-- Token 序列 (简化表示)
[FUNCTION, ON_USE, (, ),
 LOCAL, COMBO, =, GET_COUNTER, (, "diluc_e_combo", ),
 IF, COMBO, >=, N_2, THEN,
   DAMAGE, (, ACTIVE_ENEMY, N_5, PYRO, ),
   CLEAR_COUNTER, (, "diluc_e_combo", ),
 ELSE,
   DAMAGE, (, ACTIVE_ENEMY, N_3, PYRO, ),
   INC_COUNTER, (, "diluc_e_combo", N_1, ),
 END,
 END]

-- 长度约 50-100 个 token
```

## 5. 网络输入

```python
def get_observation(game_state, active_char):
    # 1. 基础状态
    state_vec = encode_state(game_state)  # [HP, 能量, 附着, ...] 100维
    
    # 2. 技能代码 (每个角色4个技能)
    skill_codes = []
    for skill in active_char.skills:
        tokens = tokenizer.tokenize(skill.lua_code)
        skill_codes.append(tokens)  # [4, 128]
    
    return {
        'state': state_vec,
        'skills': skill_codes,
    }
```

## 6. 与之前方案对比

| 方案 | Token数 | 平均代码长度 | 表达能力 |
|------|---------|-------------|----------|
| 复杂 JSON | N/A | 极长 | 强 |
| 通用 Lua | 200+ | 200+ | 极强 |
| **固定 API** | **80** | **50-100** | **足够** |

## 7. Go 实现

```go
// 注册 API 到 Lua
func (l *LuaRuntime) RegisterAPI() {
    l.RegisterFunction("damage", apiDamage)
    l.RegisterFunction("heal", apiHeal)
    l.RegisterFunction("set_counter", apiSetCounter)
    l.RegisterFunction("get_counter", apiGetCounter)
    // ... 共20个
}

// API 实现
func apiDamage(L *lua.State) int {
    target := L.ToInteger(1)
    amount := L.ToInteger(2)
    element := L.ToInteger(3)
    
    ctx := getContext(L)
    ctx.World.DealDamage(EntityID(target), amount, Element(element))
    
    return 0  // 无返回值
}

func apiSetCounter(L *lua.State) int {
    name := L.ToString(1)
    value := L.ToInteger(2)
    
    ctx := getContext(L)
    ctx.Side.SetCounter(name, value)
    
    return 0
}
```

---

**总结**: 20个固定 API，80个 token，足够表达所有角色技能。
