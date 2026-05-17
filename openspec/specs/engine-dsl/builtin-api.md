---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
parent: ./spec.md
---

# Builtin API — Lua subset + builtin function 列表 + 注册要求

> 治理 [`./spec.md`](./spec.md) invariant #11 / #12 / #13 / #14。
> DSL syntax = Lua 的严格子集(无 closure / 无 metatable / 无 stdlib)。
> Builtin function 列表为 engine 与 DSL 之间的硬接口契约。新 builtin
> 加入 SHALL 在 tokenize + eval 两侧同时注册,SHALL 走 OpenSpec change。

## 1. DSL Lua subset

### 1.1 Allowed constructs

DSL SHALL only use the following Lua constructs(详
`gicg_engine/interp/lexer.go` + `parser.go`):

- `local` 变量声明
- `if` / `elseif` / `else` / `return` 控制流
- `and` / `or` / `not` 布尔运算
- 比较运算符:`==`, `~=`, `<`, `<=`, `>`, `>=`
- 算术运算符:`+`, `-`, `*`, `/`, `%`(integer-only,实现见 lexer)
- 匿名函数:`function(ctx) ... end`(callback 形式)
- Table literal:`{key=value, ...}`
- Builtin functions:`min`, `max`(+ engine-registered builtins,详 §3)

### 1.2 Forbidden constructs

DSL SHALL NOT use any of(详 `memory feedback_lua_dsl_constraints`):

- 循环:`for`, `while`, `repeat`
- 迭代器:`pairs`, `ipairs`
- Math stdlib:`math.*`
- Length operator:`#`
- **Named function definitions**:`function name() ... end`(顶层 function
  禁止;只允许匿名 callback 形式 `function(ctx) ... end`)
- Closure return:`return function() ... end`(builtin 接 lambda 路线
  已证伪)
- Metatable:`setmetatable`, `rawset`, `rawget`
- String / table / IO stdlib:`string.*`, `table.*`, `io.*`
- **顶层全局表赋值**:`_G.x = ...`
- **Global variable writes**:任何不带 `local` 的赋值在 file-isolation 下
  SHALL 报错(`Runtime.ExecFileSandboxed` 隔离 env)

### 1.3 Subset 实施位置

- **Lexer**(`gicg_engine/interp/lexer.go`)— token whitelist
- **Parser**(`gicg_engine/interp/parser.go`)— grammar subset
- **Eval**(`gicg_engine/interp/eval.go`)— runtime semantics
- **ExecFileSandboxed**(`gicg_engine/interp/loader.go`)— file isolation:
  - Can READ builtin APIs / enums(registered via `RegisterBuiltins`)
  - Writes stay in file-local env
  - Cross-file sharing only through `declare_counter` / `get_counter` /
    `declare_skill` / `get_skill` / `get_char`

## 2. Builtin registration 要求

### 2.1 双侧注册原则

Builtin APIs SHALL be registered via `RegisterBuiltins` in
`gicg_engine/interp/builtins.go`。

**Critical**:tokenize 认 ≠ eval 认。新 builtin SHALL 在两侧同时注册
(详 `memory feedback_builtin_registration_audit`):

1. **Tokenize 侧**:lexer SHALL recognize 函数名为 identifier(自动,
   通常无需改 lexer)。但若 builtin 与 keyword 冲突,SHALL 显式 ignore
   keyword 优先级。
2. **Eval 侧**:`RegisterBuiltins` SHALL 绑定 function name 到 Go
   implementation,否则 eval 时报 `unknown function`。

### 2.2 Counter parameter 类型断言

Builtin 接受 counter ref 作为参数时,SHALL 用类型断言验证(详
`memory feedback_builtin_registration_audit`):

```go
counter, ok := args[0].(*CounterProxy)
if !ok { return ErrTypeMismatch }
```

SHALL NOT silently accept 任何 `Value` 类型 — type confusion 会导致
runtime panic。

### 2.3 Lua syntax 限制对 builtin 设计的反向约束

由于 DSL 不允许 closure return / 顶层 function,builtin API SHALL
adopt 以下设计:

- **Callback 形式接 lambda**:`on_xxx(function(ctx) ... end)`
- **Group / proxy 接 method chain**:`counter:get()` 而非
  `get(counter)`
- **方法链终止于 setter / getter**,不返回 closure 链(无法在 DSL 内
  存储 / 调用)

## 3. Builtin API 列表

以下列表为 DSL 作者可调用的全部 builtin。每条 SHALL 在
`gicg_engine/interp/builtins.go` 注册,签名与本 spec 一致;不一致 SHALL
作为 bug 修复(优先改 engine),不改本 spec(本 spec 是契约)。

### 3.1 Counter

```lua
declare_counter(name, scope, value [, {min, max, tag}])
get_counter(name, scope [, Player.Enemy])
get_counter_group(tag)
register_on_tag_write(tag, "before"|"after", op, fn)
```

**Counter methods**(返回值为 `CounterProxy` / `SelfSlotProxy` / group proxy):

```lua
:get()  :set(v)  :add(v)  :sub(v)  :cmin()  :cmax()
:get_at(p)  :set_at(p, v)            -- PerPlayer
:get_at(p, c)  :set_at(p, c, v)      -- PerChar
:decay_all(p)  :fill_all(p, v)       -- PerChar batch
```

详 [`./counter.md`](./counter.md)。

### 3.2 Entity

```lua
declare_char(name, {hp, max_energy, element, weapon})
bind_char(name, player_idx, char_idx)
get_char(name)
-- char methods:
--   :hp() :energy()                -- 返回 counter proxy
--   :owner_player() :owner_char()  -- 返回 int idx
--   :alive() :name() :element() :weapon()
declare_skill(char, name, ap [, energy [, opts]])
get_skill(char, name)
invoke_skill(skill_id)
declare_card(name, ap [, {target, battle_action, requires_char,
                          requires_weapon, slot}])
get_card(name)
add_card(card_ref, zone [, player])
```

详 [`./skill-pattern.md`](./skill-pattern.md)。

### 3.3 Action

```lua
deal_damage(target, element, value [, opts])
heal(target, value)
invoke_skill(skill_id [, {paid=true}])
defer_fn(fn)
get_active_char(player)
set_active_char(player, char)
get_next_char(player, char)
context_player()
force_switch_next(player)
register_on_all_hp(op, fn)
register_on_all_energy(op, fn)
```

`deal_damage` / `heal` SHALL use `Target.*` enum,SHALL NOT 直接传 HP
counter ref(详 §3.4)。

#### 3.3.1 Action semantics

每个 action builtin 的运行时语义 SHALL conform to 下表(实现于
`gicg_engine/interp/builtins.go`):

| Function | Semantics |
|----------|-----------|
| `deal_damage(target, element, value [, opts])` | Enters damage pipeline (`HookDamageBoost` → `HookReactionDamage` → `HookDamageReduce` → HP write → `HookAfterDamage`,详 [`./damage.md`](./damage.md))。`opts = {penetrate, source}` SHALL override inherited event frame fields。 |
| `heal(target, value)` | Symmetric with damage,uses `HookBeforeHeal` / `HookAfterHeal`,不进 damage pipeline。 |
| `invoke_skill(skill_id [, {paid=true}])` | Re-enters `HookSkillUse` with the current frame's `Source` inherited(例 `刻印` invoked by `复刻` keeps `SrcCard`)。`paid=true` SHALL skip cost deduction(silent invoke 路径;详 `memory feedback_dsl_sentinels_silent_invoke`)。 |
| `defer_fn(fn)` | Append callback to current event layer's deferred queue。SHALL execute after current hook returns but before the layer is popped。 |
| `set_active_char(player, char)` / `force_switch_next(player)` / `get_active_char(player)` / `get_next_char(player, char)` | Active-char bookkeeping;SHALL emit `HookSwitch` only when active char changes。 |
| `context_player()` | Returns the frame's current context player(`Player.Own` / `Player.Enemy` resolution anchor)。 |
| `register_on_all_hp(op, fn)` / `register_on_all_energy(op, fn)` | Shorthands that register `on_before_write` / `on_after_write` hooks on every known HP / energy counter — used by `system/` files to implement global HP / energy contracts(死亡检测 / 大招触发 etc.)。 |

### 3.4 Target enum

所有 `deal_damage` / `heal` SHALL use `Target.*` enum,SHALL NOT use
HP counter refs:

```lua
Target.EnemyActive   Target.EnemyAll      Target.EnemyNonActive
Target.OwnActive     Target.OwnAll        Target.CardTarget
```

### 3.5 Enums

```lua
Element.None / Fire / Ice / Water / Electro / Geo / Physical
Tag.Summon / Element / Equip / Food / Support / Shield
Player.Own / Enemy / All
Zone.Hand / Deck
Scope.Self / ActiveStatus / PerChar / PerPlayer / Global
Op.Set / Add / Sub
Source.Skill / Card / Status / Summon / Support / Reaction
Weapon.None / Sword / Polearm / Bow
```

### 3.6 Hooks

Hook signature(详 [`./hook.md`](./hook.md)):

```lua
on_xxx(fn)                  -- default priority 0
on_xxx(priority, fn)        -- explicit priority
```

Damage pipeline hooks(详 [`./damage.md`](./damage.md)):

```lua
on_damage_boost  on_reaction_damage  on_damage_reduce  on_after_damage
```

Action / turn hooks:

```lua
on_action_check  on_action_prepare  on_skill_use  on_card_play
on_switch  on_before_turn_flip
```

Round phase hooks(per-player auto-dispatched,详
[`./skill-pattern.md`](./skill-pattern.md) §3.4):

```lua
on_round_start  on_round_end  on_round_end_post_summon
on_round_end_decay  on_round_end_final
```

Counter write hooks:

```lua
on_before_write(counter, op, fn)
on_after_write(counter, op, fn)
```

### 3.7 Ref types — DSL never sees int ID

DSL callbacks SHALL receive ref handles only:

- `*SkillRef`(`gicg_engine/interp/registry.go` L131)
- `*CardRef`(`gicg_engine/interp/registry.go` L172)
- `LazySkillRef`(`gicg_engine/interp/proxies_char.go` L220)— talent
  cards 用 lazy ref

DSL SHALL NOT access `.id` / `.Ref` 等内部 int field。Ref 比较通过
pointer identity(`==`)。Counter metadata 存 ref 用 `ref_kind` 元数据
区分类型,SHALL NOT 暴露 `.id` 字段。

详 `memory feedback_ctx_skill_index_type`(DSL only sees ref, never
int ID)。

## 4. Builtin 加入流程

新 builtin 加入 SHALL 走以下步骤(P0 期间人工 SOP,P1+ 工具化):

1. **OpenSpec change 提案** — `openspec/changes/<id>/` 含 proposal +
   spec delta(`openspec/changes/<id>/specs/engine-dsl/spec.md` 增加
   SHALL 项 / `openspec/changes/<id>/specs/engine-dsl/builtin-api.md`
   增加 API 行)
2. **Tasks**:
   - 在 `gicg_engine/interp/builtins.go` 注册 function
   - 在 lexer / parser 若需要(通常不需要,仅当与 keyword 冲突)
   - 写测试覆盖 happy + edge case
3. **Verify**:
   - DSL 文件中使用新 builtin,跑 e2e 测试通过
   - 类型断言到位(对应 §2.2)
4. **Archive** — `/opsx:archive <change-id>` 合并 spec delta 到本文件

## 5. Cross-reference

- Lua syntax 限制详 `memory feedback_lua_dsl_constraints`
- Builtin 双侧注册要求详 `memory feedback_builtin_registration_audit`
- DSL only sees ref 详 `memory feedback_ctx_skill_index_type`
- ADR-0019 strict 8 时机 hook(damage pipeline)详
  [`./damage.md`](./damage.md) §1.1
- Lexer / parser / eval / loader 实现位置:
  `gicg_engine/interp/{lexer,parser,eval,builtins,loader,registry}.go`
- DSL exemplar(以牙还牙)详 `memory reference_dsl_example`
