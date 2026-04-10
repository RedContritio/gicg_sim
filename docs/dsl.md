# DSL 规范

## 1. Counter

所有游戏状态统一为 flat counter 数组。HP、能量、护盾层数、标记——运行时无语义区别。

每个 counter 包含：
- `value`：当前值
- `min`：下限（通常为 0）
- `max`：上限（如 HP 上限、护盾上限）

Counter 操作（运行时原语）：
- `counter:get([target])` → 读取值
- `counter:set([target,] value)` → 设置值
- `counter:add([target,] value)` → 增加值
- `counter:sub([target,] value)` → 减少值
- 每次写操作自动 clamp 到 [min, max]

## 2. Hook

所有效果逻辑统一为 flat hook 数组。技能效果、状态效果、反应效果——运行时无类型区别。

Hook 注册形式：
```
-- 写入管道
on_before_write(counter, op, fn)           -- 拦截 counter 写操作，可修改/取消
on_after_write(counter, op, fn)            -- counter 写操作完成后响应

-- 伤害管道
on_before_damage(filter, fn)               -- ① 可修改 value/element/skip_reaction
on_reaction_damage(fn)                     -- ② 元素反应伤害加成（护盾前），可 defer 状态副作用
on_after_damage(filter, fn)                -- ⑤ 始终触发；filter.require_hit=true 限定实际命中

-- 动作系统
on_action_check(filter, fn)                -- 动作可用性检查（ctx.playable 默认 true，置 false 阻止）
on_action_prepare(filter, fn)              -- 动作预处理（可修改 ctx.ap_cost/energy_cost/battle_action）
on_skill_use(filter, fn)                   -- 技能效果
on_card_play(card_ref, fn)                 -- 卡牌效果
on_switch(filter, fn)                      -- 切换角色事件（action_context 区分主动/强制）
on_before_turn_flip(filter, fn)            -- 行动权翻转前（可修改 ctx.battle_action）

-- 回合阶段
on_round_start(fn)                         -- 回合开始（round.lua: AP 重置、先手判定）
on_round_end(fn)                           -- 结束阶段：状态结算
on_round_end_post_summon(fn)               -- 结束阶段：召唤物结算
on_round_end_decay(fn)                     -- 结束阶段：持续时间衰减
on_round_end_final(fn)                     -- 结束阶段：抽牌后最终结算

-- 通用
on_action(filter, fn)                      -- 任意玩家动作（通用兜底）
```

DSL 声明函数（声明/获取模式：首次调用创建，后续同参数调用返回已有引用，参数冲突报错）：
```
declare_char(name, opts)                   -- 声明角色：创建 HP/能量 counter，注册相关 hook
declare_skill(char, name, ap [,energy [,opts]])  -- 声明技能：返回 skill index，注册 ActionCheck/Prepare
declare_card(name, ap [, opts])            -- 声明卡牌：返回 card ref，注册 ActionCheck/Prepare
```

DSL 控制函数：
```
set_winner(player)                         -- 设置胜者并结束游戏
set_alive(char_ref, bool)                  -- 设置角色存活状态（death.lua 使用）
defer(fn)                                  -- 将效果追加到当前事件帧的延后队列
draw_card(player, count)                   -- 抽牌（draw.lua 使用）
```

Hook 分发机制：
- `on_before_write` / `on_after_write` 通过 dispatch table 按 counter 引用索引
- 写 `counter[i]` 时只触发注册在 `counter[i]` 上的 hook
- 同类型 hook 按**注册顺序**执行（先注册先执行，无 priority 机制）
- `on_before_write` 中调用 `cancel()` 可中止本次写操作

**执行顺序保证：**
- 宏观顺序由管道阶段（HookType）决定，如伤害管道 ①-⑥ 是不同 HookType
- 微观隔离由 counter 绑定决定，不同 counter 上的 hook 互不干扰
- 同类型 hook 按确定性加载顺序执行：`system/` → `characters/角色.lua` → `characters/角色_技能.lua` → `cards/`
- 同一文件内按声明顺序

## 3. Counter Scope（仅编写期）

Scope 是 DSL 编写期的语法糖，初始化时展开为 flat 实例：

| Scope | 展开方式 | 示例 |
|-------|---------|------|
| `self` | 所属角色 1 个实例 | HP、能量 |
| `active_status` | 每方出战角色状态区 1 个实例 | 护盾、增益 |
| `per_char` | 每个角色 1 个实例 | 元素附着 |
| `per_own_char` | 己方每个角色 1 个实例 | |
| `per_enemy_char` | 敌方每个角色 1 个实例 | 蝶印、正电/负电 |
| `per_player` | 每个玩家 1 个实例 | AP、行动计数 |
| `global` | 全局 1 个实例 | 回合数 |

展开后全部为 flat counter。例如 3v3 中 `per_enemy_char` 的 counter 展开为 3 个具体实例，hook 引用重写为 branch + 索引选择。

## 4. 声明/获取模式

`create_counter` 和 `declare_skill` / `declare_card` 均遵循**声明/获取模式**：

- **首次调用**：创建资源（counter / skill / card），注册相关 hook，存入 registry
- **后续同参数调用**：校验参数一致，返回已有引用，不重复注册 hook
- **参数不一致**：立即 error（声明冲突）

Counter 去重 key = `owner_player:owner_char:name`。Skill 去重 key = `char_name:skill_name`。Card 去重 key = `name`。

每个技能/卡牌文件在顶部独立声明自己需要的 counter 和 skill handle，文件完全自包含。跨文件共享通过声明/获取机制自动实现，无需集中的 `counters.lua`。例如 `赤蝶_蝶火.lua` 和 `赤蝶_回火.lua` 各自 `create_counter("蝶火_active", Scope.Self, 0, {min=0, max=1})` 同名 counter，加载后指向同一实例。

技能引用同理：`赤蝶_蝶火.lua` 通过 `declare_skill(赤蝶, "枪", 3)` 获取已有枪的 skill index，用于注册加伤 hook。

## 5. 预加载 API

引擎在加载 DSL 文件前预加载全局常量和函数：

```lua
-- 枚举常量（strict_enum，拼写错误立即报错，不可赋值）
Element = { None, Fire, Ice, Water, Electro, Geo, Physical }
Op      = { Set, Add, Sub }
Action  = { UseSkill, PlayCard, Switch, ForcedDeath, ForcedReaction }
Source  = { Skill, Card, Status, Summon, Support, Reaction }
Scope   = { Self, ActiveStatus, PerChar, PerOwnChar, PerEnemyChar, PerPlayer, Global }
Filter  = { Self, Active }
Target  = { EnemyActive, EnemyAll, OwnAll }

-- 实体声明（声明/获取模式）
declare_char(name, opts)              -- 创建角色，自动创建 HP/能量 counter
declare_skill(char, name, ap [, energy [, opts]])  -- 声明技能，返回 skill index
declare_card(name, ap [, opts])       -- 声明卡牌，返回 card ref

-- 实体引用
get_char(name) -> char_ref
get_card(name) -> card_ref

-- Counter 创建（声明/获取模式）
create_counter(name, scope, value [, {min, max}]) -> counter  -- 默认 min=0, max=255

-- 伤害/治疗（push 事件帧，进入引擎管道）
deal_damage(target, element, value, [opts])  -- opts: penetrate, source, actor
heal(target, value, [opts])                  -- opts: source, actor

-- 实体操作（push 事件帧）
switch_active(char_ref)
invoke_skill(char_ref, skill_index)
create_summon(opts, hooks_fn)
create_support(opts, hooks_fn)
destroy_entity(entity_ref)

-- Hook 注册（见第 2 节完整列表）
on_before_write, on_after_write
on_before_damage, on_reaction_damage, on_after_damage
on_action_check, on_action_prepare, on_before_turn_flip
on_skill_use, on_card_play, on_switch
on_round_start, on_round_end, on_round_end_post_summon,
on_round_end_decay, on_round_end_final
on_action

-- 控制
cancel()                              -- on_before_write 中取消写操作
defer(fn)                             -- 追加到当前事件帧的延后队列
set_winner(player)                    -- 设置胜者并结束游戏
set_alive(char_ref, bool)             -- 设置角色存活状态
draw_card(player, count)              -- 抽牌

-- 查询
get_enemy_alive() -> list
get_own_alive() -> list

-- 角色引用方法（由 declare_char 创建的 counter 提供）
char_ref:alive() -> bool
char_ref:active() -> bool
char_ref:hp() -> counter
char_ref:hp_max() -> counter
char_ref:energy() -> counter
```

## 6. 文件结构

```
data/
  characters/
    赤蝶/
      赤蝶.lua              -- 角色声明：HP 上限、能量上限等元数据
      赤蝶_枪.lua           -- 纯基础效果（declare_skill + damage）
      赤蝶_蝶火.lua         -- buff 拥有其所有效果（附魔/加伤/回火条件治疗/衰减）
      赤蝶_回火.lua         -- 纯基础效果
    墨客/ 猫咪/ 刻师傅/ 天星/  -- 同上结构
  cards/
    L1/ 碌碌无为.lua
    L2/ 美味烧鸡.lua, 佛跳墙.lua, 占星.lua, 诅咒.lua
    L3/ 速速茶点.lua, 铁剑.lua, 铁枪.lua, 荷花酥.lua, 以牙还牙.lua, 反制.lua
    L4/ 铁弓.lua, 西风长枪.lua, 西风剑.lua, 瞬身之术.lua, 伏兵之术.lua,
        清洁时间.lua, 玄冰.lua
    L5/ 蝶鳞.lua, 守正.lua, 刺刺猫爪.lua, 发现静电.lua, 星愿.lua
    L6/ 以逸待劳.lua, 乘胜追击.lua, 以攻代守.lua
  system/
    reactions/
      蒸发.lua, 超载.lua, 融化.lua, 感电.lua, 冻结.lua, 超导.lua, 结晶.lua
    round.lua               -- AP counter 创建、回合开始 AP 重置、先手判定
    death.lua               -- on_after_write(hp, SUB) 检测 HP≤0 → set_alive → defer 强制切换
    energy.lua              -- 回合开始能量分配、技能命中获取能量
    frozen.lua              -- on_action_check 检查冻结 counter → 阻止技能和切换
    draw.lua                -- 开局抽 5 张、on_round_end_final 抽 2 张
    timeout.lua             -- 记录第一回合先手方、on_round_end_final 判负
    food.lua                -- 饱腹 counter、on_action_check 阻止再次使用食物
  patches/
    ...                     -- 平衡策略 DSL
```

## 7. 卡牌分级

分级服务于训练课程，核心指标为 **该牌对 agent 的学习难度 = 效果复杂度 x 策略前置依赖**。

| 级别 | 分级标准 | 卡牌 |
|------|---------|------|
| **L1** | 无效果，纯填充 | 碌碌无为 |
| **L2** | 即时单次效果，agent 只需学"现在用还是以后用" | 美味烧鸡、佛跳墙、占星、诅咒 |
| **L3** | 追踪使用次数或回合内状态，效果跨多步生效 | 速速茶点、铁剑、铁枪、荷花酥、以牙还牙、反制 |
| **L4** | 涉及切换/召唤物/能量传递等系统联动 | 铁弓、西风长枪、西风剑、瞬身之术、伏兵之术、清洁时间、玄冰 |
| **L5** | 改写角色核心技能行为，需完全理解对应角色技能循环 | 蝶鳞、守正、刺刺猫爪、发现静电、星愿 |
| **L6** | 改变全局策略流派，需在理解全部机制基础上重新规划打法 | 以逸待劳、乘胜追击、以攻代守 |

## 8. 完整 DSL 示例

### 8.1 猫爪护盾 + 刺刺猫爪

```lua
-- characters/猫咪/猫咪.lua
declare_char("猫咪", { hp = 10, max_energy = 3, element = Element.Ice })
```

```lua
-- characters/猫咪/猫咪_猫爪护盾.lua
local 猫咪             = get_char("猫咪")
local 猫爪护盾         = create_counter("猫爪护盾", Scope.ActiveStatus, 0, { min = 0, max = 4 })
local 刺刺猫爪_active  = create_counter("刺刺猫爪_active", Scope.Self, 0, { min = 0, max = 1 })
local 刺刺猫爪_trigger = create_counter("刺刺猫爪_trigger", Scope.Self, 0, { min = 0, max = 2 })
local 猫爪 = declare_skill(猫咪, "猫爪护盾", 3)

on_round_start(function(ctx)
  刺刺猫爪_trigger:set(0)
end)

on_skill_use({ actor = Filter.Self, skill = 猫爪 }, function(ctx)
  deal_damage(Target.EnemyActive, Element.Ice, 1)
  猫爪护盾:add(2)
end)

on_before_write(猫咪:hp(), Op.Sub, function(ctx)
  if ctx.penetrate then return end
  local shield = 猫爪护盾:get()
  if shield <= 0 then return end

  local absorb = math.min(shield, ctx.value)
  猫爪护盾:sub(absorb)
  ctx.value = ctx.value - absorb
end)
```

```lua
-- cards/L5/刺刺猫爪.lua
local 猫咪             = get_char("猫咪")
local 猫爪护盾         = create_counter("猫爪护盾", Scope.ActiveStatus, 0, { min = 0, max = 4 })
local 刺刺猫爪_active  = create_counter("刺刺猫爪_active", Scope.Self, 0, { min = 0, max = 1 })
local 刺刺猫爪_trigger = create_counter("刺刺猫爪_trigger", Scope.Self, 0, { min = 0, max = 2 })
local 猫爪 = declare_skill(猫咪, "猫爪护盾", 3)  -- 获取已有 skill handle

local 刺刺猫爪 = declare_card("刺刺猫爪", 3)

on_card_play(刺刺猫爪, function(ctx)
  刺刺猫爪_active:set(1)
  invoke_skill(猫咪, 猫爪)
end)

on_after_write(猫爪护盾, Op.Sub, function(ctx)
  if 刺刺猫爪_active:get() <= 0 then return end
  if 刺刺猫爪_trigger:get() >= 2 then return end

  if 猫爪护盾:get() > 0 then
    猫爪护盾:add(1)
  else
    deal_damage(Target.EnemyActive, Element.None, 1, { penetrate = true })
  end
  刺刺猫爪_trigger:add(1)
end)
```

### 8.2 刻师傅静电体 + 复刻

```lua
-- characters/刻师傅/刻师傅.lua
declare_char("刻师傅", { hp = 10, max_energy = 3, element = Element.Electro })
```

```lua
-- cards/L5/发现静电.lua
local 刻师傅        = get_char("刻师傅")
local 静电体_active = create_counter("静电体_active", Scope.Self, 0, { min = 0, max = 1 })
local 正电          = create_counter("正电", Scope.PerEnemyChar, 0, { min = 0, max = 2 })
local 负电          = create_counter("负电", Scope.PerEnemyChar, 0, { min = 0, max = 2 })
local 刻印 = declare_skill(刻师傅, "刻印", 3)  -- 获取刻印 skill handle
local 剑   = declare_skill(刻师傅, "剑", 3)
local 雷暴 = declare_skill(刻师傅, "雷暴", 3, 3)

local 发现静电 = declare_card("发现静电", 1)

on_card_play(发现静电, function(ctx)
  静电体_active:set(1)
  invoke_skill(刻师傅, 刻印)
end)

on_skill_use({ actor = Filter.Self, skill = 刻印, action_context = Action.UseSkill }, function(ctx)
  if 静电体_active:get() > 0 then
    负电:add(Target.EnemyActive, 1)
  end
end)

on_skill_use({ actor = Filter.Self, skill_mask = {剑, 雷暴} }, function(ctx)
  if 静电体_active:get() > 0 then
    正电:add(Target.EnemyActive, 1)
  end
end)
```

```lua
-- cards/L4/复刻.lua
local 刻师傅        = get_char("刻师傅")
local 静电体_active = create_counter("静电体_active", Scope.Self, 0, { min = 0, max = 1 })
local 正电          = create_counter("正电", Scope.PerEnemyChar, 0, { min = 0, max = 2 })
local 负电          = create_counter("负电", Scope.PerEnemyChar, 0, { min = 0, max = 2 })
local 刻印 = declare_skill(刻师傅, "刻印", 3)

local 复刻 = declare_card("复刻", 0)

on_action_check({ card_ref = 复刻 }, function(ctx)
  if not 刻师傅:alive() then
    ctx.playable = false
  end
end)

on_card_play(复刻, function(ctx)
  if 静电体_active:get() > 0 then
    local pos = 正电:get(Target.EnemyActive)
    local neg = 负电:get(Target.EnemyActive)

    if pos > neg then
      正电:sub(Target.EnemyActive, 1)
      负电:sub(Target.EnemyActive, 1)
      ctx.cost = ctx.cost - 1
    elseif pos == neg and pos > 0 then
      正电:sub(Target.EnemyActive, 1)
      负电:sub(Target.EnemyActive, 1)
      heal(刻师傅, 1)
    end
  end

  switch_active(刻师傅)
  invoke_skill(刻师傅, 刻印)
end)
```

### 8.3 水云 + 守正 + 泼墨

```lua
-- characters/墨客/墨客.lua
declare_char("墨客", { hp = 10, max_energy = 2, element = Element.Water })
```

```lua
-- characters/墨客/墨客_墨意.lua
local 墨客        = get_char("墨客")
local 水云        = create_counter("水云", Scope.ActiveStatus, 0, { min = 0, max = 10 })
local 守正_active = create_counter("守正_active", Scope.Self, 0, { min = 0, max = 1 })
local 墨意 = declare_skill(墨客, "墨意", 3)

on_skill_use({ actor = Filter.Self, skill = 墨意 }, function(ctx)
  deal_damage(Target.EnemyActive, Element.Water, 1)
  水云:add(2)
end)

on_before_write(墨客:hp(), Op.Sub, function(ctx)
  if ctx.penetrate then return end
  if 水云:get() <= 0 then return end
  if ctx.value < 3 then return end

  水云:sub(1)
  ctx.value = ctx.value - 1
end)
```

```lua
-- characters/墨客/墨客_水龙吟.lua
local 墨客        = get_char("墨客")
local 泼墨        = create_counter("泼墨", Scope.ActiveStatus, 0, { min = 0, max = 10 })
local 泼墨_rounds = create_counter("泼墨_rounds", Scope.ActiveStatus, 0, { min = 0, max = 10 })
local 守正_active = create_counter("守正_active", Scope.Self, 0, { min = 0, max = 1 })
local 正气        = create_counter("正气", Scope.Self, 0, { min = 0, max = 2 })
local 水龙吟 = declare_skill(墨客, "水龙吟", 3, 2)

on_skill_use({ actor = Filter.Self, skill = 水龙吟 }, function(ctx)
  if 守正_active:get() > 0 then
    deal_damage(Target.EnemyActive, Element.Water, 2)
  end
  泼墨:set(2)
  泼墨_rounds:set(2)
end)

on_after_damage({ actor = Filter.Active, source = Source.Skill }, function(ctx)
  if 泼墨:get() <= 0 then return end

  deal_damage(Target.EnemyActive, Element.Water, 2, { source = Source.Status })
  泼墨:sub(1)

  if 守正_active:get() > 0 then
    正气:add(1)
  end
end)
```

```lua
-- cards/L5/守正.lua
local 墨客        = get_char("墨客")
local 水云        = create_counter("水云", Scope.ActiveStatus, 0, { min = 0, max = 10 })
local 守正_active = create_counter("守正_active", Scope.Self, 0, { min = 0, max = 1 })
local 正气        = create_counter("正气", Scope.Self, 0, { min = 0, max = 2 })
local 水龙吟 = declare_skill(墨客, "水龙吟", 3, 2)  -- 获取 skill handle

local 守正 = declare_card("守正", 2)

on_card_play(守正, function(ctx)
  守正_active:set(1)
  invoke_skill(墨客, 水龙吟)
end)

-- 守正.lua 作为卡牌后于技能加载，但此 hook 注册在 水云.SUB 上，
-- 而护盾吸收 hook 注册在 墨客:hp().SUB 上，二者不冲突
on_before_write(水云, Op.Sub, function(ctx)
  if 守正_active:get() <= 0 then return end
  if 正气:get() <= 0 then return end

  正气:sub(1)
  cancel()
end)

on_round_end_post_summon(function(ctx)
  if 正气:get() > 0 then
    正气:sub(1)
  end
end)
```

### 8.4 赤蝶蝶火 + 蝶鳞

每个技能文件完全自包含：所需 counter/skill 直接在文件顶部声明，引擎按同名去重共享。
**Buff 拥有其所有效果**：蝶火.lua 包含附魔/加伤/回火条件治疗，回火.lua 只含纯基础效果。

```lua
-- characters/赤蝶/赤蝶.lua
declare_char("赤蝶", { hp = 10, max_energy = 3, element = Element.Fire })
```

```lua
-- characters/赤蝶/赤蝶_枪.lua（纯基础效果）
local 赤蝶 = get_char("赤蝶")
local 枪 = declare_skill(赤蝶, "枪", 3)

on_skill_use({ actor = Filter.Self, skill = 枪 }, function(ctx)
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
```

```lua
-- characters/赤蝶/赤蝶_蝶火.lua（buff 拥有其所有效果）
local 赤蝶        = get_char("赤蝶")
local 蝶火_active = create_counter("蝶火_active", Scope.Self, 0, { min = 0, max = 1 })
local 蝶火_rounds = create_counter("蝶火_rounds", Scope.Self, 0, { min = 0, max = 10 })
local 蝶鳞_active = create_counter("蝶鳞_active", Scope.Self, 0, { min = 0, max = 1 })
local 蝶印        = create_counter("蝶印", Scope.PerEnemyChar, 0, { min = 0, max = 1 })

-- 获取枪和回火的 skill handle（声明/获取模式）
local 枪 = declare_skill(赤蝶, "枪", 3)
local 回火 = declare_skill(赤蝶, "回火", 3, 3)
local 蝶火 = declare_skill(赤蝶, "蝶火", 3)

on_skill_use({ actor = Filter.Self, skill = 蝶火 }, function(ctx)
  deal_damage(赤蝶:hp(), Element.None, 1, { penetrate = true })
  蝶火_active:set(1)
  蝶火_rounds:set(2)
end)

-- 附魔：物理 → 火
on_before_damage({ actor = Filter.Self, source = Source.Skill }, function(ctx)
  if 蝶火_active:get() > 0 and ctx.element == Element.Physical then
    ctx.element = Element.Fire
  end
end)

-- 枪加伤 +2
on_before_damage({ actor = Filter.Self, source = Source.Skill, skill = 枪 }, function(ctx)
  if 蝶火_active:get() > 0 then
    ctx.value = ctx.value + 2
  end
end)

-- 蝶鳞：枪命中时附加蝶印
on_after_damage({ actor = Filter.Self, source = Source.Skill, skill = 枪 }, function(ctx)
  if 蝶鳞_active:get() > 0 and 蝶火_active:get() > 0 then
    蝶印:set(ctx.target, 1)
  end
end)

-- 回火条件治疗（蝶火状态下 HP < 50%）
on_after_damage({ actor = Filter.Self, skill = 回火 }, function(ctx)
  if 蝶火_active:get() <= 0 then return end
  local hp = 赤蝶:hp():get()
  local hp_max = 15  -- TODO: 从 counter max 读取
  if hp >= hp_max / 2 then return end

  local base_heal = 2
  if 蝶鳞_active:get() > 0 then base_heal = 3 end
  heal(赤蝶:hp(), base_heal)

  if 蝶鳞_active:get() > 0 and 蝶印:get(Target.EnemyActive) > 0 then
    deal_damage(Target.EnemyActive, Element.Fire, 1, { source = Source.Status })
  end
end)

-- 蝶印回合结算
on_round_end(function(ctx)
  for _, target in ipairs(get_enemy_alive()) do
    if 蝶印:get(target) > 0 then
      deal_damage(target, Element.Fire, 1, { source = Source.Status })
      蝶印:set(target, 0)
    end
  end
end)

-- 持续时间衰减
on_round_end_decay(function(ctx)
  if 蝶火_active:get() > 0 then
    蝶火_rounds:sub(1)
    if 蝶火_rounds:get() <= 0 then
      蝶火_active:set(0)
    end
  end
end)
```

```lua
-- characters/赤蝶/赤蝶_回火.lua（纯基础效果，条件治疗由蝶火.lua 负责）
local 赤蝶 = get_char("赤蝶")
local 回火 = declare_skill(赤蝶, "回火", 3, 3)

on_skill_use({ actor = Filter.Self, skill = 回火 }, function(ctx)
  deal_damage(Target.EnemyActive, Element.Fire, 4)
end)
```

```lua
-- cards/L5/蝶鳞.lua
local 赤蝶        = get_char("赤蝶")
local 蝶鳞_active = create_counter("蝶鳞_active", Scope.Self, 0, { min = 0, max = 1 })
local 蝶火 = declare_skill(赤蝶, "蝶火", 3)  -- 获取 skill handle

local 蝶鳞 = declare_card("蝶鳞", 2)

on_card_play(蝶鳞, function(ctx)
  蝶鳞_active:set(1)
  invoke_skill(赤蝶, 蝶火)
end)
```
