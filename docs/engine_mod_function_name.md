# Mod 函数名引用设计

## 核心简化

> **attach_mod(event, function_name) - 用函数名代替匿名函数。**

```lua
-- 之前：匿名函数
attach_mod("end_phase", function()
    if oz_uses:get() <= 0 then return end
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:dec(1)
end)

-- 现在：函数名引用
function on_oz_trigger()
    if oz_uses:get() <= 0 then return end
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:dec(1)
end

attach_mod("end_phase", "on_oz_trigger")
```

## 1. 新 Lua 格式

### 菲谢尔

```lua
-- fischl_e.lua

-- 1. 定义 Counter
local oz_uses = create_counter(0, 2)

-- 2. 定义 Mod 处理函数
function mod_oz_trigger()
    if oz_uses:get() <= 0 then
        return
    end
    
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:dec(1)
end

-- 3. 注册 Mod
attach_mod("end_phase", "mod_oz_trigger")

-- 4. 定义技能函数
function on_use()
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:set(2)
end
```

### 迪卢克

```lua
-- diluc_e.lua

local e_combo = create_counter(0, 2)

-- Mod：回合结束重置连击
function mod_reset_combo()
    if e_combo:get() > 0 then
        e_combo:clear()
    end
end

attach_mod("round_end", "mod_reset_combo")

-- 技能
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

### 阿蕾奇诺 (多 Mod)

```lua
-- arlecchino_passive.lua

local life_debt = create_counter(0, 10)

-- Mod 1：战斗开始给敌方上血偿勒令
function mod_battle_start()
    for _, enemy in ipairs(query(ALL_ENEMIES)) do
        local debt = create_target_counter(enemy, 0, 5)
        debt:set(3)
    end
end

attach_mod("on_battle_start", "mod_battle_start")

-- arlecchino_attack.lua

local life_debt = get_counter("life_debt")

-- Mod 2：元素转换
function mod_infusion(ctx)
    if life_debt:get() <= 0 then
        return
    end
    if ctx.damage.element ~= PHYSICAL then
        return
    end
    
    ctx.damage.element = PYRO
    ctx.damage.amount = ctx.damage.amount + 1
end

attach_mod("on_damage_calc", "mod_infusion")

-- 技能
function on_use()
    local dmg = 2
    
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

function mod_shield_block(ctx)
    if ctx.target ~= SELF then
        return
    end
    
    local shield_val = shield:get()
    if shield_val <= 0 then
        return
    end
    
    local block = math.min(shield_val, ctx.damage.amount)
    ctx.damage.amount = ctx.damage.amount - block
    shield:dec(block)
end

attach_mod("on_damage_receive", "mod_shield_block")

function on_use()
    damage(ACTIVE_ENEMY, 2, CRYO)
    shield:set(2)
end
```

## 2. Go 引擎存储结构

### 预扫描提取

```go
// SkillScript - 解析后的脚本
type SkillScript struct {
    CardID string
    
    Counters []CounterDef   // create_counter 调用
    
    Mods []ModDef           // attach_mod 注册
    // Mod 处理函数源码单独存储
    ModHandlers map[string]string  // 函数名 -> 源码
    
    SkillFunc string        // on_use 函数名
    SkillSource string      // on_use 源码
}

type ModDef struct {
    ID       string  // 如 "mod_oz_trigger"
    Event    string  // "end_phase"
    Handler  string  // 函数名 "on_oz_trigger"
    Source   string  // 函数源码 (用于RL观察)
}
```

### 扫描器实现

```go
func (s *Scanner) Scan(luaCode string) (*SkillScript, error) {
    script := &SkillScript{
        ModHandlers: make(map[string]string),
    }
    
    // 1. 提取所有函数定义
    funcPattern := regexp.MustCompile(`function\s+(\w+)\s*\((.*?)\)([\s\S]*?)end`)
    matches := funcPattern.FindAllStringSubmatch(luaCode, -1)
    
    handlers := make(map[string]string)
    for _, m := range matches {
        funcName := m[1]
        funcBody := m[3]
        handlers[funcName] = funcBody
    }
    
    // 2. 提取 attach_mod 调用
    modPattern := regexp.MustCompile(`attach_mod\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)`)
    modMatches := modPattern.FindAllStringSubmatch(luaCode, -1)
    
    for _, m := range modMatches {
        event := m[1]
        funcName := m[2]
        
        if body, ok := handlers[funcName]; ok {
            script.Mods = append(script.Mods, ModDef{
                ID:      funcName,
                Event:   event,
                Handler: funcName,
                Source:  body,  // 存储源码
            })
            script.ModHandlers[funcName] = body
        }
    }
    
    // 3. 提取 on_use 函数
    if body, ok := handlers["on_use"]; ok {
        script.SkillFunc = "on_use"
        script.SkillSource = body
    }
    
    return script, nil
}
```

### Mod 运行时

```go
type ModInstance struct {
    Def      ModDef
    Handler  *lua.FunctionRef
}

// 初始化时加载所有 Mod 函数
func (w *World) LoadMods(script *SkillScript) {
    for _, modDef := range script.Mods {
        // 编译 Mod 处理函数
        handler := w.lua.CompileFunction(modDef.Source)
        
        instance := &ModInstance{
            Def:     modDef,
            Handler: handler,
        }
        
        w.Mods[modDef.Event] = append(w.Mods[modDef.Event], instance)
    }
}

// 触发事件
func (w *World) TriggerEvent(event string, ctx *EventContext) {
    for _, mod := range w.Mods[event] {
        w.lua.CallFunction(mod.Handler, ctx)
    }
}
```

## 3. RL 观察值编码

```python
def encode_skill_mods(skill_script):
    """编码技能的 Mod 源码"""
    obs = []
    
    # 每个技能最多 3 个 Mod
    for i in range(3):
        if i < len(skill_script.Mods):
            mod = skill_script.Mods[i]
            # Tokenize Mod 函数源码
            tokens = tokenizer.tokenize(mod.Source)
            obs.extend(tokens)
        else:
            # 填充
            obs.extend([PAD_TOKEN] * 64)
    
    return obs

# 总观察值
observation = {
    'state': encode_game_state(world),      # 基础状态
    'skill_code': tokenize(skill.Source),   # 技能函数
    'mod_codes': encode_skill_mods(skill),  # Mod 函数列表
}
```

## 4. 存储格式示例

```json
{
  "card_id": "fischl",
  "counters": [
    {"name": "oz_uses", "default": 0, "max": 2}
  ],
  "mods": [
    {
      "id": "mod_oz_trigger",
      "event": "end_phase",
      "handler": "mod_oz_trigger",
      "source": "\n    if oz_uses:get() <= 0 then\n        return\n    end\n    \n    damage(ACTIVE_ENEMY, 1, ELECTRO)\n    oz_uses:dec(1)\n"
    }
  ],
  "skill_func": "on_use",
  "skill_source": "\n    damage(ACTIVE_ENEMY, 1, ELECTRO)\n    oz_uses:set(2)\n"
}
```

## 5. 优势

| 特性 | 匿名函数 | 函数名引用 |
|------|---------|-----------|
| 可读性 | 嵌套混乱 | 清晰分离 |
| 源码提取 | 需解析 AST | 正则提取即可 |
| 复用性 | 无法复用 | 可复用函数 |
| 调试 | 难定位 | 函数名直接定位 |
| 存储 | 整段代码 | 结构化存储 |

## 6. 完整菲谢尔 (最终版)

```lua
-- fischl_e.lua

local oz_uses = create_counter(0, 2)

function mod_oz_trigger()
    if oz_uses:get() <= 0 then return end
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:dec(1)
end

attach_mod("end_phase", "mod_oz_trigger")

function on_use()
    damage(ACTIVE_ENEMY, 1, ELECTRO)
    oz_uses:set(2)
end
```

---

**极简设计**: 清晰结构，易提取，易存储，约 50 个 token。
