---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
parent: ./spec.md
---

# Counter system — scope / declare-get / groups / tags / 使用规则

> 治理 [`./spec.md`](./spec.md) invariant #2 / #3 / #4 / #13。
> Counter 是 DSL 中表达 persistent game state(buff / stack / status /
> 资源池等)的核心机制。Engine 自身不知 HP / energy,所有 game term
> 通过 counter + hook 在 DSL 中表达。

## 1. Usage Guidelines — 什么该用 counter

Counters represent **persistent game state that the engine doesn't already
track**。Before declaring a counter, check:

### 1.1 SHALL NOT use counter for

#### 1.1.1 Shadow state of engine-managed data

Engine 已 track hands / decks / chars alive / turn / round。SHALL NOT mirror
these in counters — SHALL use query APIs。Shadow counter SHALL drift out of
sync 当 state changes via paths you didn't anticipate(e.g., `复刻_in_hand`
breaks if the card is lost via enemy discard or hand-size overflow)。

Query APIs(详 [`./builtin-api.md`](./builtin-api.md)):

- `has_card_in_hand(player, card_ref)` — hand contents
- `get_active_char(player)`, `get_next_char(player, char)` — active char
- `char:alive()`, `char:hp():get()`, `char:energy():get()` — char state
- `get_turn()`, `get_round()` — turn / round

#### 1.1.2 Transient state within a single event chain

If a value only matters for the duration of one skill / card invocation and
its nested effects,SHALL use the existing event context fields instead of
counter flags:

- `ctx.source` — `Source.Skill`, `Source.Card`, `Source.Reaction`,
  `Source.Summon`, `Source.Support` — tells you *what kind* of thing
  invoked the current event
- `ctx.skill_index`, `ctx.card_ref` — exactly which skill / card
- `ctx.actor_player`, `ctx.actor_char` — who acted
- `ctx.action_context` — whether this is a switch, skill use, card play, etc.

**Example (BAD)**:creating `复刻_mode` counter to mark "刻印 is being
invoked via 复刻", setting / unsetting it around `invoke_skill`。This breaks
if anything nested re-enters,and leaks internal details as counters。

**Example (GOOD)**:in `invoke_skill`,the new frame inherits the caller's
`Source`。The 刻印 hook checks `if ctx.source == Source.Card then return end`
to detect card-invoked usage。Zero counters needed。

### 1.2 SHALL use counter for

- **Persistent buffs / stacks / status** that outlive a single event chain
  (`蝶火_active`, `刻印_enchant`, `猫爪护盾`, element attachments)
- **Cross-event accumulators**(round counters, cooldowns, resource pools)
- **Things the engine explicitly delegates**(HP, energy, AP, alive flags —
  these *are* the canonical state)

### 1.3 Rule of thumb

If the counter is only read / written inside a single `on_skill_use` /
`on_card_play` invocation(including its nested `invoke_skill` /
`deal_damage`),it SHALL NOT exist — SHALL use `ctx.*` fields or direct
queries instead。

## 2. Scope

Counter scope SHALL be one of 5 enum values。每 scope 的 key 结构与
access API:

| Scope | Expansion | Key | Access |
|-------|-----------|-----|--------|
| `Self` / `ActiveStatus` | 1 counter per char binding | `player:char:name` | `:get()`, `:set(v)`, `:cmin()`, `:cmax()` |
| `PerPlayer` | 2 counters(per player) | `name` | `:get()`(auto via context),`:get_at(p)`, `:set_at(p, v)` |
| `PerChar` | 2 × MAX_CHARS counters | `name` | `:get_at(p, c)`, `:set_at(p, c, v)`, `:decay_all(p)`, `:fill_all(p, v)` |
| `Global` | 1 counter | `name` | `:get()`, `:set(v)` |

All counter types SHALL support `:cmin()`, `:cmax()` to read bounds。

### 2.1 Key uniqueness rule

PerPlayer / PerChar / Global keys SHALL NOT include owner context — name
alone identifies the counter。Self / ActiveStatus keys SHALL include
`player:char:` prefix internally(详 [`./skill-pattern.md`](./skill-pattern.md)
"Self / ActiveStatus 共享 SlotIDs" 段)。

## 3. Declare vs get

### 3.1 declare-or-get pattern

- `declare_counter(name, scope, value, {min, max, tag})` — creates the
  counter on first call,returns existing on subsequent calls。On repeat
  declare,params SHALL completely match,otherwise engine SHALL panic
  (`unresolved_dependency` / `parameter mismatch`)。
- `get_counter(name, scope[, bind])` — returns existing or errors with
  `unresolved_dependency:name`。Optional `bind`(e.g. `Player.Enemy`)
  returns a view proxy bound to the given player perspective。

### 3.2 Cross-file sharing

Counters declared in one DSL file SHALL be observable from another file via
`get_counter(name, scope)`。Engine resolves declare / get topologically at
load time(详 主 spec.md cross-reference)。`get_counter` SHALL error if
no `declare_counter` for the name exists,never silently create。

## 4. Counter groups & tags

### 4.1 Group access

- `get_counter_group(tag)` — returns group proxy for all counters with
  given tag。
- Group methods:`:get()`, `:set(v)`, `:add(v)`, `:sub(v)`。Operate on
  non-zero entries only,scoped to context player。
- Group `_at({player=...})`:table filter with `Player.Own` / `Player.Enemy` /
  `Player.All`。
- `register_on_tag_write(tag, "before"|"after", op, fn)` — register write
  hooks on all tagged counters。

### 4.2 Tag enum

Counter tags SHALL be drawn from(详 [`./builtin-api.md`](./builtin-api.md)
"Enums" 段):

- `Tag.Summon` — 召唤物 lifecycle counters
- `Tag.Element` — element attachment counters
- `Tag.Equip` — equip slot counters
- `Tag.Food` — food buff counters
- `Tag.Support` — 支援区 counters
- `Tag.Shield` — shield absorption counters

## 5. Player constants in `_at`

PerPlayer / PerChar `_at` 方法 SHALL accept `Player.Own`,`Player.Enemy`
in addition to absolute indices(0,1)。

`Player` enum 值与语义:

- `Player.Own`(-10)— context player
- `Player.Enemy`(-11)— opponent of context player
- `Player.All`(-12)— both(group ops only)

Resolved dynamically via `_current_context_player` engine state。Context
player SHALL be set automatically by the engine when dispatching hooks /
running counter ops within a skill / card pipeline。

## 6. Counter callbacks & write hooks

### 6.1 on_before_write / on_after_write

- `on_before_write(counter_ref, op, fn)` — fires before counter mutation;
  fn 可以修改 `ctx.value` 修正写入值。
- `on_after_write(counter_ref, op, fn)` — fires after counter mutation;
  read-only,常用于 trigger 衍生效果(如护盾 `:sub()` 后检查剩余值)。

### 6.2 Self / ActiveStatus write context

Write hooks on Self / ActiveStatus counters SHALL see
`CurrentContextPlayer` / `OwnerChar` 等于 counter owner(NOT
`ctx.actor_player`)。例:猫爪护盾的 `on_after_write(Sub)` reads the
shield owner's `active:get()` rather than the attacker's。详
[`./skill-pattern.md`](./skill-pattern.md) "Self / ActiveStatus 共享
SlotIDs" 段。

## 7. Examples

### 7.1 Persistent buff with min/max bound

```lua
local 蝶火_active = declare_counter("蝶火_active", Scope.Self, 0,
  {min=0, max=3, tag=Tag.Element})

on_skill_use(function(ctx)
  if ctx.skill_index ~= 飞舞 then return end
  蝶火_active:cmax():set(蝶火_active:get() + 1)
end)
```

### 7.2 Cross-event group accumulator

```lua
local 食物_used = declare_counter("食物_used", Scope.PerChar, 0,
  {min=0, max=1, tag=Tag.Food})

-- Round-end decay
on_round_end_decay(function(ctx)
  食物_used:decay_all(Player.All)
end)
```

### 7.3 Anti-pattern — shadow state(BAD,SHALL NOT)

```lua
-- BAD: 复刻_in_hand drifts when enemy discards or hand overflows
local 复刻_in_hand = declare_counter("复刻_in_hand", Scope.PerPlayer, 0)

on_card_play(function(ctx)
  if ctx.card_ref == 复刻 then
    复刻_in_hand:set_at(ctx.actor_player, 0)
  end
end)
```

应改为直接查 `has_card_in_hand(player, 复刻)`。

### 7.4 Anti-pattern — transient flag(BAD,SHALL NOT)

```lua
-- BAD: 复刻_mode counter to mark "刻印 is being invoked via 复刻"
local 复刻_mode = declare_counter("复刻_mode", Scope.Global, 0)

on_card_play(function(ctx)
  if ctx.card_ref == 复刻 then
    复刻_mode:set(1)
    invoke_skill(刻印)
    复刻_mode:set(0)  -- breaks on nested re-entry
  end
end)
```

应改为 hook 内检查 `ctx.source == Source.Card`。
