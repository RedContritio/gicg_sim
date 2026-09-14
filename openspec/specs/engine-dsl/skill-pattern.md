---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
parent: ./spec.md
---

# Skill pattern — registration / mirror filter / talent / DSL load caching

> 治理 [`./spec.md`](./spec.md) invariant #9 / #10 / #14。
> Skill / card 是 DSL 中最复杂的 declare-and-bind 模式。Mirror match
> (same char on both sides)+ talent card(`requires_char`)各引入不同
> 的 load / dispatch 规则,SHALL 一致遵循以下约定,否则会出现重复注册。

## 1. Skill registration

### 1.1 declare-or-get pattern

Skills SHALL be declared via:

```lua
declare_skill(char, name, ap [, energy [, opts]])
```

返回 `*SkillRef`(详 `gicg_engine/interp/registry.go` L131)。重复
declare 参数 SHALL 完全匹配,否则 engine SHALL panic。

引用现有 skill:

```lua
get_skill(char, name)  -- 返回 *SkillRef
```

`get_skill` SHALL error if no `declare_skill` exists with the name —
SHALL NOT silently create。

### 1.2 Skill identity

Skill index SHALL be globally unique auto-increment(详
`CLAUDE.md "Core Model"` 段)。`ctx.skill_index` SHALL be sufficient
to identify any skill。

Skill identity 比较 SHALL be by ref equality(pointer identity):

```lua
if ctx.skill_index == 枪 then ... end
```

SHALL NOT use integer ID 字段 — DSL only sees ref handle,不暴露 `.id`。

### 1.3 SkillRef 字段

`SkillRef`(`gicg_engine/interp/registry.go` L131)包含:

- `ID` — internal int,DSL SHALL NOT access
- `Name` — skill 名(string)
- `CharName` — owner char 名
- `Cost` — dice cost + energy(`engine.Cost` 结构)

DSL SHALL 仅通过 ref handle 传递 skill 标识,SHALL NOT 解构内部字段。

## 2. Card registration

### 2.1 declare-or-get pattern

Cards SHALL be declared via:

```lua
declare_card(name, ap [, {target, battle_action, requires_char,
                          requires_weapon, slot}])
```

返回 `*CardRef`(详 `gicg_engine/interp/registry.go` L172)。

引用现有 card:

```lua
get_card(name)  -- 返回 *CardRef
```

### 2.2 CardRef 字段

`CardRef` 字段(详 `gicg_engine/interp/registry.go` L172):

- `Ref` — 0-based internal identity; serialized fields use `-1` as the
  missing-reference sentinel
- `Name`、`Cost`、`BattleAction`、`TargetMode`、`RequiresWeapon`、
  `RequiresChar`、`Slot`(`SlotNone` / `SlotEquip` / `SlotSupport` /
  `SlotSpecialty`)

### 2.3 Slot 语义

CardSlot enum(`gicg_engine/interp/registry.go` L162)由 engine
on_action_check / on_card_play 强制:

- `SlotNone` — ordinary action card,进 hand → fire → discard
- `SlotEquip` — weapon / artifact / talent,per-char 1 each
- `SlotSupport` — 支援区,per-player 4 max
- `SlotSpecialty` — 特技,per-char 1(详
  [`0012-specialty-and-prepare-skill`](../../changes/archive/0012-specialty-and-prepare-skill/))

## 3. Mirror match — per-binding load + actor filter

### 3.1 Load 模型

Character DSL files under `data/pools/<pool_id>/characters/<name>/` SHALL be
loaded **per-binding** — 一次每 owner slot。Mirror matchup(same char on
both sides)SHALL execute each file twice,registering each hook twice。

### 3.2 Actor-centric hook 过滤要求

Actor-centric hooks SHALL filter events to the loading owner via
`ctx.actor_player` / `ctx.actor_char` comparison。否则 effects double-fire
on mirror(#152 bug class)。

需要 mirror filter 的 hook:

- `on_skill_use`
- `on_damage_boost`(attacker-side phase)
- `on_card_play`
- attacker-side `on_after_damage`
- `on_action_check` of own candidates

### 3.3 Canonical exemplar

```lua
-- 定义技能的文件
local 赤蝶 = get_char("赤蝶")
local my_player = 赤蝶:owner_player()
local my_char = 赤蝶:owner_char()

local 枪 = declare_skill(赤蝶, "枪", 3)

on_skill_use(function(ctx)
  -- #152 mirror-match filter: skip events produced by the other
  -- side's binding of this same file.
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then
    return
  end
  if ctx.skill_index ~= 枪 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
```

```lua
-- 引用技能的文件
local 枪 = get_skill(赤蝶, "枪")
```

### 3.4 PerPlayerHooks — 不需要 actor filter

PerPlayerHooks events SHALL be dispatched per-owner automatically — no
actor filter needed:

- `on_round_start`
- `on_round_end` / `on_round_end_post_summon` / `on_round_end_decay` /
  `on_round_end_final`
- `on_before_turn_flip`

Engine SHALL set context player before dispatch,DSL hook 直接看到
context-bound 状态。

## 4. Card DSL — global load

### 4.1 Ordinary card

Cards under `data/pools/<pool_id>/cards/` SHALL be loaded globally
(once,not per-binding)。Card DSL files 不需要 mirror filter。

### 4.2 Talent card

Talent cards(`requires_char = "X"` in `declare_card`)SHALL be loaded
globally(once),resolve owner slots dynamically at hook-fire time via:

- `SelfSlotProxy` — counter access bound to current context player
- `LazyCharProxy` — char ref lazy resolution
- `LazySkillRef` — skill ref lazy resolution(`gicg_engine/interp/
  proxies_char.go` L220)

Mirror match(both sides run X)SHALL be supported with no per-binding
load。

### 4.3 Talent uniqueness filter

`filterTalentCardsForSlotUniqueness` in `gicg_engine/capi/capi.go` SHALL
drop only "k==0" entries(nobody has X);k≥1 SHALL be kept。

## 5. Self / ActiveStatus 共享 SlotIDs

`Scope.Self` / `Scope.ActiveStatus` counters SHALL be keyed
`"<charName>:<counterName>"` internally,with a shared
`CounterEntry.SlotIDs[2*MaxChars]int` table。Population:

- **Per-binding char-file declares** — populate one slot at a time
- **Talent declares** — populate all slots at once(shared load)

### 5.1 Proxy 类型差异

- **Per-binding** `get_counter` SHALL return single-slot `CounterProxy`。
- **Shared-load talent** `get_counter` SHALL return `SelfSlotProxy` —
  lazily resolves via `(CurrentContextPlayer, find_slot(player,
  OwnerName))` at each access。

### 5.2 Write hook context

Write hooks on Self / ActiveStatus counters SHALL see
`CurrentContextPlayer` / `OwnerChar` 等于 counter owner(NOT
`ctx.ActorPlayer`)。例:猫爪护盾的 `on_after_write(Sub)` reads the
shield owner's `active:get()` rather than the attacker's。

## 6. char-skill topo constraint

char DSL files SHALL NOT call `get_card("X")` for static analysis reasons:

- Topo 静态扫描 architectural constraint — load-order resolver 仅扫
  `declare_*` / `get_*` 配对。
- 反向用法:如果 card 需要引用 char,SHALL 在 card file 用
  `sharedFiles` declaration,而非 char file 引 card。

## 7. DSL load caching

### 7.1 Process-level cache

All `.lua` files under the configured `data_dir` SHALL be parsed once
per process and cached in `gicg_engine/interp/loader.go`。First `GameNew`
populates the cache;subsequent `GameNew` calls SHALL reuse the parsed AST。

### 7.2 Cache never invalidates

Cache SHALL never invalidate during a process lifetime — mid-run DSL edits
SHALL be **intentionally** not visible。Re-load requires process restart。

### 7.3 Eager preload

Recommended at training launch:

```bash
.venv/bin/python -c "from gicg_env.engine import preload_dsl; \
                     preload_dsl('data')"
```

The cache also fills lazily on first engine construction. Callers that need to
exclude first-game parse cost MAY call `preload_dsl` explicitly; training does
not depend on eager preload for cache correctness.

## 8. Cross-reference

- Counter scope / declare-get / SlotIDs 详 [`./counter.md`](./counter.md)
- Hook dispatch / filter 详 [`./hook.md`](./hook.md)
- Damage pipeline ordering 详 [`./damage.md`](./damage.md)
- Builtin API 签名详 [`./builtin-api.md`](./builtin-api.md)
- `Runtime.LoadFilesWithDeps` 拓扑加载详主 [`./spec.md`](./spec.md) §5
  cross-references(待 engine-runtime spec 落地)
- DSL exemplar: `data/pools/v_legacy/cards/L3/以牙还牙.lua`
- Specialty / prepare-skill history:
  [`0012-specialty-and-prepare-skill`](../../changes/archive/0012-specialty-and-prepare-skill/)
- Mirror-match behavior is governed by this file's §3 and covered by engine
  tests; issue numbers alone are historical context.
