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

DSL SHALL NOT use any of the following constructs:

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

**Critical**:tokenize 认 ≠ eval 认。新 builtin SHALL 在两侧同时注册:

1. **Tokenize 侧**:lexer SHALL recognize 函数名为 identifier(自动,
   通常无需改 lexer)。但若 builtin 与 keyword 冲突,SHALL 显式 ignore
   keyword 优先级。
2. **Eval 侧**:`RegisterBuiltins` SHALL 绑定 function name 到 Go
   implementation,否则 eval 时报 `unknown function`。

### 2.2 Counter parameter 类型断言

Builtin 接受 counter ref 作为参数时,SHALL 用类型断言验证:

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
apply_element(target, element) -- 纯附着：只执行反应/附着与非伤害后果
invoke_skill(skill_id [, {paid=true}])
defer_fn(fn)
get_active_char(player)
is_char_alive(player, char) -- boolean; invalid slot returns false
set_active_char(player, char)
get_next_char(player, char)
context_player()
force_switch_next(player)
force_switch_previous(player) -- 向前循环跳过阵亡角色；复用强制切换事件与暂停/恢复
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
| `invoke_skill(skill_id [, {paid=true}])` | Re-enters `HookSkillUse` with the current frame's `Source` inherited(例 `刻印` invoked by `复刻` keeps `SrcCard`)。`paid=true` SHALL skip cost deduction;the source-inheritance pattern is detailed in [`counter.md`](./counter.md) §1.2。 |
| `defer_fn(fn)` | Append callback to current event layer's deferred queue。SHALL execute after current hook returns but before the layer is popped。 |
| `set_active_char(player, char)` / `force_switch_next(player)` / `get_active_char(player)` / `get_next_char(player, char)` | Active-char bookkeeping;SHALL emit `HookSwitch` only when active char changes。 |
| `context_player()` | Returns the frame's current context player(`Player.Own` / `Player.Enemy` resolution anchor)。 |
| `register_on_all_hp(op, fn)` / `register_on_all_energy(op, fn)` | Shorthands that register `on_before_write` / `on_after_write` hooks on every known HP / energy counter — used by `system/` files to implement global HP / energy contracts(死亡检测 / 大招触发 etc.)。 |

用户确认（2026-09-12）：强制切换也 SHALL 派发 `HookSwitch`；实际未改变出战角色
时 SHALL NOT 派发。规则自动切换使用 `ActForcedReaction`，死亡选人使用
`ActForcedDeath`，均不额外扣骰或翻转行动权。主动切换专属效果仍可按 ActionContext
过滤；事件派发本身不跳过强制切换。会请求玩家输入的原生调用 SHALL 位于
`Step` / `ExecuteEffect` 等 managed boundary 内，以保留暂停后的剩余效果。

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

DSL callbacks only see reference handles, never raw integer IDs.

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

- Lua syntax 限制详本文件 §1。
- Builtin 双侧注册要求详本文件 §2。
- DSL reference identity 详 [`./skill-pattern.md`](./skill-pattern.md) §1.3。
- ADR-0019 strict 8 时机 hook(damage pipeline)详
  [`./damage.md`](./damage.md) §1.1
- Lexer / parser / eval / loader 实现位置:
  `gicg_engine/interp/{lexer,parser,eval,builtins,loader,registry}.go`
- DSL exemplar: `data/pools/v_legacy/cards/L3/以牙还牙.lua`

## 费用总量减免（2026-09-11）

`cost_reduce(ctx, amount)` SHALL 减少最多 amount 个骰子费用，按指定元素
（枚举顺序）、同色、无色的顺序扣减。非正费用槽不占用减免额度；不能
将正费用减为负数。amount SHALL 为非负整数，错误参数 SHALL 报错。
不修改能量费用。调用 SHALL 将当前 hook ID 记录到 AppliedMods，包括
零减免，用于执行后消费或计数；查询阶段不得直接推进持久计数。
Tokenizer / IR builtin ID 为 312。参见 `verify-current-cards` change。

## 条件伤害目标（2026-09-11）

`deal_damage(target, element, value, {target_counter = counter, source = ...})`
支持可选 target_counter，必须是数值型 PerChar counter，否则报错。先按
原 target 解析目标，再于首击之前筛选该 counter >0 的角色；未选角色
不产生伤害或反应事件。保留原发起者、逐个目标和死亡选择恢复流程。
不隐式修改筛选 counter；标记清除由 DSL 显式执行。
IR SHALL 保留筛选计数绑定，关键字 token 为 265。
见 `confirm-current-card-rules-v2` change。

## Ordered buff instances (v4)

`register_buff(counter, opts)` binds aggregate state; options include `duration`, `progress`,
`expires_round_end`, `remove_on_death`, and `independent` (zero-valued template).
`on_xxx({order=counter, priority=0}, fn)` binds the consuming/effect hook to that instance.
`order_on="target"` selects the target's buff for target-triggered events.
Write hooks also accept options before the callback:
`on_after_write(counter, Op.Sub, {order=buff}, fn)` and
`register_on_tag_write(Tag.Shield, "after", Op.Add, {order=buff}, fn)`.

`spawn_buff(template, value, duration[, player, char])` creates an independent layer;
`buff_duration()` reads the current layer, `set_buff_duration(n)` updates it (0 removes, -1 permanent).
Within a bound hook, counter reads/writes address that layer. Outside it, reads sum layers;
only set(0) is permitted for bulk removal. Duration decay is explicit in the bound decay hook.

`spawn_support_buff(template, value, duration)` SHALL create an independent instance
bound to the support that just entered in the current card-play callback. It accepts
a PerPlayer template, exposes no lifecycle ID, and rejects already-bound supports.
`remove_support(player, card)` from that instance's bound hook SHALL remove its own
support; outside an instance hook it removes the first matching support. Removal
also clears that support's associated buff, preserving other same-name instances.
Support/buff associations SHALL survive clone/checkpoint and clear on reset.
Token 359 identifies `spawn_support_buff`; internal association IDs SHALL NOT be NN inputs.

A support card played into four occupied slots SHALL enumerate the selected own
replacement slot jointly with payment. The chosen support's lifecycle identity
is captured before payment; later slot shifts SHALL NOT change that choice.
Its linked effect leaves before the new support enters with a fresh identity.
Action reference field 2 uses `-2 - ObsBuffRows - support_slot`; NN target lookup
SHALL gather the own support entity row, not an enemy row or a live buff position.
C API, Go actor and MCTS identities use aux=`ObsBuffRows + support_slot`,
target_player=actor, target_char=-1. Exact action records preserve the slot,
including slot zero, with an explicit `has_support_target` flag.

`buff_progress()` / `set_buff_progress(n)` SHALL read/write the current live
independent instance's progress (nonnegative int32). Counter-backed aggregate
effects continue using their declared progress counter. Tokens 360/361 identify
these operations. Progress is preserved through clone/checkpoint and visible in
buff observation field 5. A bound support row also carries its effect value in
field 3 and progress in field 5; field 4 remains the support's age. No raw ID is exposed.
`get_dice_total(player)` (token 362) returns the current sum across dice colors.
`ctx.reaction_kind` (token 363) is available to the rule encoder as well as the executor.

`declare_card(..., {target="enemy_summon"})` SHALL enumerate a joint card/payment/
live enemy summon choice. `selected_buff()` (token 364) returns the chosen effect's
counter proxy for `get/set/add/sub`; it SHALL NOT refer to the currently executing
buff. Selection preserves instance identity across payment; a removed target is null.
Action references use field 2 = `-2 - live_buff_position` for buff-target cards;
`-1` remains no target and nonnegative character slots retain their meaning.
NN actions SHALL gather the chosen instance's live rule/state tokens. C API, Go
actor and MCTS identities use aux=live_buff_position, target_player=owner,
target_char=-1, preserving separate summon choices under payment deduplication.

`background_energy(player)` (365) reads total energy on living background characters.
`transfer_energy_from_background(player, amount, max_sources)` (366) snapshots
living background donors in slot order, consumes up to amount from each positive
donor (at most max_sources), then gains the actually consumed total on the original
active character. Donor consumption SHALL NOT stop at the receiver's energy cap;
the receiver's ordinary gain/clamp applies, allowing overflow. The card's legality
hook separately checks whether the receiver is full or no donor has energy.

`choose_reroll(player, times)` (367) SHALL pause the current managed rule for
owner-controlled dice selection. Nonempty colors are visited in dice-color order,
with quantities 0..available, then an explicit confirmation. Selection does not
pay dice or advance RNG. Confirmation replaces selected dice with uniform rolls;
subsequent rerolls can select dice retained previously. Remaining rule hooks resume
after all selections; neither card payment nor discard is repeated.
`ActionReroll` (5) semantic references are `[5, quantity, color]`, where color 8
means confirmation with quantity 0. Field 1 is NOT a rule-hook reference for this
kind. C API, Go actor and MCTS use identity subject=quantity, aux=color. Payment
remains zero. The NN uses quantity features and a separate color/confirmation
embedding; own execution entities expose pool, selected counts, current color
and remaining rolls, while the opponent receives no private selection data.
Records SHALL preserve exact color and quantity. In-process snapshots/clones
support waiting selection; archival checkpoints retain the existing prohibition
on exporting/importing replay continuations.

`deal_damage(..., {actor=char_proxy})` explicitly supplies damage ownership and the viewpoint
for relative targets. Used for reactions to events initiated by the other player.

Current provisional cross-player round order and NN contract:
[Buff lifecycle v4](../../changes/buff-lifecycle-v4/design.md).

## 纯附着与原目标相对选择（2026-09-14）

`apply_element` SHALL 与 `deal_damage` 区分。纯附着的反应回调收到只读
`ctx.attachment_only = true`，SHALL 不产生伤害事件或反应附加伤害；冻结、
强制切换等非伤害后果仍可执行。反应规则 SHALL 在创建伤害分支前检查此字段。
最终伤害被护盾吸收不等同纯附着，不能用最终HP差决定是否运行反应。

`deal_damage(character, element, value, {other_characters=true})` SHALL 对该角色
同队其他存活角色造成伤害，排除原目标而非当前出战角色。用于超导/感电，
也适用于主目标原本就在后台或后续改变出战位置的情况。

## 原生天赋技能来源（2026-09-14）

`invoke_skill(skill, {source=Source.Skill})` SHALL 显式覆盖调用来源，用于原生天赋的立即使用技能。
未指定source时继续继承原调用来源；调用本身不再次扣骰子/能量，天赋牌自身须声明正确费用和能量要求。
普通/元素战技仍增加一次能量。`heal(character, value)` 支持明确的存活角色引用，以免技能后出战变化导致治疗错人。
穿透伤害 SHALL 跳过元素类型修改与伤害加成阶段，也不经过反应和减伤阶段；不得因来源是技能而获得增伤。
