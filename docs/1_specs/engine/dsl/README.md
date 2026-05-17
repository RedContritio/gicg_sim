> **MOVED to `openspec/specs/engine-dsl/`**(2026-05-15,P1-T5)
>
> 本文档内容已迁到 OpenSpec(SHALL 语言):
> - [Spec](../../../../openspec/specs/engine-dsl/spec.md)
> - 详 Subtopics index(counter / hook / damage / skill-pattern /
>   builtin-api / file-structure)
>
> 卡牌难度分级(原 structure.md §7)→
> `docs/3_plans/cards/card_difficulty_grades.md`
>
> 本文件保留至 P1++;**只读**。

---

# DSL 规范

DSL 规范的入口。完整规范拆分为多个子文档：

- 本文：核心模型 (Counter, Hook, Scope, 声明/获取)
- [api.md](api.md) — 预加载 API 一览（完整列表在 top-level `CLAUDE.md`）
- [structure.md](structure.md) — 文件结构与卡牌分级

Live DSL examples: read `data/pools/v_legacy/characters/<name>/*.lua`
and `data/pools/v_legacy/cards/L*/*.lua` directly. The canonical "read
this first" example is `data/pools/v_legacy/cards/L3/以牙还牙.lua` — it
demonstrates declare_counter, Player binding, summon lifecycle, and
hook registration with no magic numbers. Pool layout (ADR-0011): all
cards/chars live under `data/pools/<pool_id>/`; loader walks the
parent chain in `manifest.toml` and folds overrides + removes.

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

Hook 注册形式 (canonical list in top-level `CLAUDE.md` "API" block; this
is a shorthand reminder, not the complete list):
```
-- 写入管道
on_before_write(counter, op, fn)           -- 拦截 counter 写操作，可 cancel()
on_after_write(counter, op, fn)            -- counter 写操作完成后响应

-- 伤害管道（详见 ../README.md §4）
on_damage_boost(fn)                        -- ① 增伤（附魔/加伤），可修改 value/element
on_reaction_damage(fn)                     -- ② 元素反应
on_damage_reduce(fn)                       -- ③ 减伤（护盾吸收），非穿透时触发
on_after_damage(fn)                        -- ⑤ 始终触发

-- 动作系统
on_action_check(fn)                        -- 可置 ctx.playable=false 阻止动作
on_action_prepare(fn)                      -- 可修改 ctx.ap_cost/energy_cost/battle_action
on_skill_use(fn)                           -- 技能效果
on_card_play(fn)                           -- 卡牌效果
on_switch(fn)                              -- 切换角色事件
on_before_turn_flip(fn)                    -- 行动权翻转前

-- 回合阶段
on_round_start(fn)
on_round_end(fn)                           -- ① 状态结算
on_round_end_post_summon(fn)               -- ② 召唤物结算
on_round_end_decay(fn)                     -- ③ 持续时间衰减
on_round_end_final(fn)                     -- ④ 抽牌后最终结算
```

**Filtering 约定**: hooks 不接受 filter table 参数 — 过滤一律在回调体内
以 early return 方式实现 (`if ctx.skill_index ~= 枪 then return end`)。
Priority 可选 (`on_xxx(priority, fn)`), 默认 0。

DSL 声明函数（声明/获取模式，详见 api.md）:
```
declare_counter(name, scope, value [, {min, max, tag}])
declare_char(name, {hp, max_energy, element, weapon})
declare_skill(char, name, ap [, energy [, opts]])
declare_card(name, ap [, {target, battle_action, requires_weapon, requires_char}])
add_card(card_ref, zone [, player])
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
| `Scope.Self` | 所属角色 1 个实例 | HP、能量、蝶火_active |
| `Scope.ActiveStatus` | 每方出战角色状态区 1 个实例 | 护盾、泼墨 |
| `Scope.PerChar` | 每个角色 1 个实例（2 × MaxChars） | 元素附着、蝶印、正电/负电 |
| `Scope.PerPlayer` | 每个玩家 1 个实例 | AP、行动计数 |
| `Scope.Global` | 全局 1 个实例 | 回合数 |

注意：没有 `PerOwnChar` / `PerEnemyChar` — `PerChar` 已覆盖全部角色，访问时通过 `:get_at(Player.Own, c)` / `:get_at(Player.Enemy, c)` 指定侧。展开后全部为 flat counter。

## 4. 声明/获取模式

`declare_counter` / `declare_char` / `declare_skill` / `declare_card`
均遵循**声明/获取模式**：首次调用创建资源并注册相关 hook；后续同参数
调用返回已有引用；参数冲突立即 error。

- Counter 去重 key：Self/ActiveStatus 是 `owner_player:owner_char:name`；PerPlayer/PerChar/Global 是 `name`（无 owner 前缀）
- Skill 去重 key：`char_name:skill_name`
- Card 去重 key：`name`

每个技能/卡牌文件顶部独立 `declare_counter` / `get_skill` 自己需要的
handle；文件自包含，无需集中的 `counters.lua`。例如 `赤蝶_蝶火.lua`
和 `赤蝶_回火.lua` 各自 `declare_counter("蝶火_active", Scope.Self, 0, {min=0, max=1})`
引用同一 counter；`declare_skill(赤蝶, "枪", 3)` 返回已有枪的 SkillRef，
可用于注册加伤 hook。

跨文件获取 (非 declare 上下文) 统一用 `get_counter` / `get_char` /
`get_skill` / `get_card` — 这些会严格校验存在性，找不到会抛
`unresolved_dependency:name`，topo loader 据此决定加载顺序。
