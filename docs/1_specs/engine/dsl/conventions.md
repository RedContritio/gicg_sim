> **MOVED to `openspec/specs/engine-dsl/`**(2026-05-15,P0-T8)
>
> 本文档内容已迁移到 OpenSpec 治理(SHALL 语言版),按 5 个 subtopic 拆分:
> - [Counter system](../../../../openspec/specs/engine-dsl/counter.md)
> - [Hook dispatch](../../../../openspec/specs/engine-dsl/hook.md)
> - [Damage pipeline](../../../../openspec/specs/engine-dsl/damage.md)
> - [Skill pattern](../../../../openspec/specs/engine-dsl/skill-pattern.md)
> - [Builtin API](../../../../openspec/specs/engine-dsl/builtin-api.md)
> - 顶层 spec:[engine-dsl/spec.md](../../../../openspec/specs/engine-dsl/spec.md)
>
> 本文件保留至 P1 阶段(`docs/1_specs/` 全量迁移),期间**只读**;
> 新增 / 修改请走 `openspec/specs/engine-dsl/` + OpenSpec change workflow。

---

# DSL 约定与 API 参考

Complete DSL reference, moved out of top-level `CLAUDE.md` to keep
the LLM-context gateway small. For the core model / declare vs get
pattern, see `README.md`; this file covers the author-facing
conventions and the full API surface.

## Counter Usage Guidelines

Counters represent **persistent game state that the engine doesn't already track**. Before declaring a counter, check:

**Don't use a counter for:**

1. **Shadow state of engine-managed data.** The engine already tracks hands, decks, chars alive, turn, round, etc. Don't mirror these in counters — use query APIs. A shadow counter will drift out of sync when state changes via paths you didn't anticipate (e.g., `复刻_in_hand` breaks if the card is lost via enemy discard or hand-size overflow).

   Query APIs:
   - `has_card_in_hand(player, card_ref)` — hand contents
   - `get_active_char(player)`, `get_next_char(player, char)` — active char
   - `char:alive()`, `char:hp():get()`, `char:energy():get()` — char state
   - `get_turn()`, `get_round()` — turn/round

2. **Transient state within a single event chain.** If a value only matters for the duration of one skill/card invocation and its nested effects, use the existing event context fields instead of counter flags:
   - `ctx.source` — `Source.Skill`, `Source.Card`, `Source.Reaction`, `Source.Summon`, `Source.Support` — tells you *what kind* of thing invoked the current event
   - `ctx.skill_index`, `ctx.card_ref` — exactly which skill/card
   - `ctx.actor_player`, `ctx.actor_char` — who acted
   - `ctx.action_context` — whether this is a switch, skill use, card play, etc.

   Example (BAD): creating `复刻_mode` counter to mark "刻印 is being invoked via 复刻", setting/unsetting it around `invoke_skill`. This breaks if anything nested re-enters, and leaks internal details as counters.

   Example (GOOD): in `invoke_skill`, the new frame inherits the caller's `Source`. The 刻印 hook checks `if ctx.source == Source.Card then return end` to detect card-invoked usage. Zero counters needed.

**Do use a counter for:**

- **Persistent buffs/stacks/status** that outlive a single event chain (`蝶火_active`, `刻印_enchant`, `猫爪护盾`, element attachments)
- **Cross-event accumulators** (round counters, cooldowns, resource pools)
- **Things the engine explicitly delegates** (HP, energy, AP, alive flags — these *are* the canonical state)

**Rule of thumb:** if the counter is only read/written inside a single `on_skill_use` / `on_card_play` invocation (including its nested `invoke_skill` / `deal_damage`), it shouldn't exist — use `ctx.*` fields or direct queries instead.

## Counter System

**Scopes:**

| Scope | Expansion | Key | Access |
|-------|-----------|-----|--------|
| `Self`/`ActiveStatus` | 1 counter | `player:char:name` | `:get()`, `:set(v)`, `:cmin()`, `:cmax()` |
| `PerPlayer` | 2 counters | `name` | `:get()` (auto), `:get_at(p)`, `:set_at(p, v)` |
| `PerChar` | 2×MAX_CHARS counters | `name` | `:get_at(p,c)`, `:set_at(p,c,v)`, `:decay_all(p)`, `:fill_all(p,v)` |
| `Global` | 1 counter | `name` | `:get()`, `:set(v)` |

All counter types support `:cmin()`, `:cmax()` to read bounds.

**declare vs get:**
- `declare_counter(name, scope, value, {min, max, tag})` — creates or returns existing (params must match)
- `get_counter(name, scope [, bind])` — returns existing or errors with `unresolved_dependency:name`. Optional `bind` (e.g. `Player.Enemy`) returns a view proxy.

PerPlayer/PerChar/Global keys do NOT include owner context. Self/ActiveStatus keys include `player:char:`.

**Player constants in `_at`:** PerPlayer/PerChar `_at` accepts `Player.Own`, `Player.Enemy` in addition to absolute indices (0, 1).

**Counter groups:**
- `get_counter_group(tag)` — returns group proxy for all counters with given tag
- Group methods: `:get()`, `:set(v)`, `:add(v)`, `:sub(v)` (only non-zero entries, context player)
- Group `_at({player=...})`: table filter with `Player.Own`/`Player.Enemy`/`Player.All`
- `register_on_tag_write(tag, "before"|"after", op, fn)` — register write hooks on all tagged counters

**Tags:** `Tag.Summon`, `Tag.Element`, `Tag.Equip`, `Tag.Food`, `Tag.Support`, `Tag.Shield`

**Player constants:** `Player.Own` (-10), `Player.Enemy` (-11), `Player.All` (-12). Resolved dynamically via `_current_context_player`.

## Damage Pipeline

```
① on_damage_boost     — 增伤（附魔、加伤），可修改 value/element
② on_reaction_damage  — 元素反应
③ on_damage_reduce    — 减伤（护盾吸收），可修改 value（仅非穿透）
④ HP write
⑤ on_after_damage     — 始终触发
```

Shields register on `on_damage_reduce` (NOT on_before_write(hp)).

## Dependency Graph

> **MOVED to `openspec/specs/engine-runtime/`**（P1-T4）：`Runtime.LoadFilesWithDeps` + `Runtime.ExecFileSandboxed` 行为已 SHALL 化抽出。本段 + 下面 "File Isolation" 段保留至 P1++ 整体清理；权威源为 [engine-runtime/spec.md](../../../../openspec/specs/engine-runtime/spec.md)。

`Runtime.LoadFilesWithDeps(paths)` in `interp/`:
1. Scans each file for `declare_counter`/`declare_char`/`declare_skill` (provides) and `get_counter`/`get_char`/`get_skill` (depends)
2. Builds dependency graph, topological sort
3. Loads files in sorted order via `Runtime.ExecFileSandboxed`

## File Isolation

DSL files loaded via `Runtime.ExecFileSandboxed` get an isolated environment:
- Can READ builtin APIs/enums (registered via `RegisterBuiltins`)
- Writes stay in file-local env
- Cross-file sharing only through `declare_counter`/`get_counter`/`declare_skill`/`get_skill`/`get_char`

## DSL Language Subset

### Allowed

`local`, `if`/`elseif`/`return`, `and`/`or`/`not`, comparisons, arithmetic, `function(ctx)...end`, `{key=value}`, `min`/`max`

### Forbidden

`for`/`while`/`repeat`, `pairs`/`ipairs`, `math.*`, `#`, named function definitions, `setmetatable`/`rawset`, `string.*`/`table.*`/`io.*`, global variable writes

## Skill Pattern

Character DSL files under `data/pools/<pool_id>/characters/<name>/` are loaded
**per-binding** — once per owner slot. Mirror matchups (same char
on both sides) execute each file twice, registering each hook
twice. Actor-centric hooks (`on_skill_use`, `on_damage_boost`,
`on_card_play`, attacker-side `on_after_damage`, `on_action_check`
of own candidates) MUST filter events to the loading owner, or
their effects double-fire on mirror. Standard shape:

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

PerPlayerHooks events (on_round_start / on_round_end* /
on_before_turn_flip) are dispatched per-owner automatically — no
actor filter needed. Cards under `data/pools/<pool_id>/cards/` are loaded globally
(once, not per-binding) so card DSL files don't need the filter
either. Talent cards (`requires_char = "X"` in `declare_card`) are
loaded globally and resolve owner slots dynamically at hook-fire
time via `SelfSlotProxy` / `LazyCharProxy` / `LazySkillRef` —
mirror matches (both sides run X) are supported with no per-
binding load. `filterTalentCardsForSlotUniqueness` in
`gicg_engine/capi/capi.go` drops only "k==0" (nobody has X);
k≥1 is kept.

Scope.Self / Scope.ActiveStatus counters are keyed
`"<charName>:<counterName>"` internally, with a shared
`CounterEntry.SlotIDs[2*MaxChars]int` table that's populated
progressively by per-binding char-file declares and all-at-once
by talent declares. Per-binding `get_counter` returns a single-
slot `CounterProxy`; shared-load talent `get_counter` returns a
`SelfSlotProxy` that lazily resolves via
`(CurrentContextPlayer, find_slot(player, OwnerName))` at each
access. Write hooks on Self/ActiveStatus counters see
`CurrentContextPlayer/OwnerChar` equal to the counter owner (not
`ctx.ActorPlayer`), so e.g. 猫爪护盾's `on_after_write(Sub)`
reads the shield owner's `active:get()` rather than the attacker's.

## DSL load caching

All `.lua` files under the configured `data_dir` are parsed once
per process and cached in `gicg_engine/interp/loader.go`. First
`GameNew` populates the cache; subsequent GameNew calls reuse the
parsed AST. Cache never invalidates during a process lifetime —
mid-run DSL edits are **intentionally** not visible.

Eager preload (recommended at training launch):

```bash
.venv/bin/python -c "from gicg_env.engine import preload_dsl; preload_dsl('data')"
```

`tools/run.py` already calls this during pre-flight, so
normal `train_az` runs are automatically immune to mid-run edits.

## Shield Pattern (on_damage_reduce)

```lua
on_damage_reduce(function(ctx)
  if ctx.target_player ~= 猫咪:owner_player() then return end
  if ctx.target_char ~= 猫咪:owner_char() then return end
  local shield = 猫爪护盾:get()
  if shield <= 0 then return end
  local absorb = min(shield, ctx.value)
  猫爪护盾:sub(absorb)
  ctx.value = ctx.value - absorb
end)
```

## API

```lua
-- Counter
declare_counter(name, scope, value [, {min, max, tag}])
get_counter(name, scope [, Player.Enemy])
get_counter_group(tag)
register_on_tag_write(tag, "before"|"after", op, fn)

-- Counter methods
:get() :set(v) :add(v) :sub(v) :cmin() :cmax()
:get_at(p) :set_at(p, v)              -- PerPlayer
:get_at(p, c) :set_at(p, c, v)        -- PerChar
:decay_all(p) :fill_all(p, v)         -- PerChar batch

-- Entity
declare_char(name, {hp, max_energy, element, weapon})
bind_char(name, player_idx, char_idx)
get_char(name)              -- :hp() :energy() :owner_player() :owner_char() :alive() :name() :element() :weapon()
declare_skill(char, name, ap [, energy [, opts]])
get_skill(char, name)
invoke_skill(skill_id)
declare_card(name, ap [, {target, battle_action}])
get_card(name)
add_card(card_ref, zone [, player])

-- Action
deal_damage(target, element, value [, opts])
heal(target, value)
defer_fn(fn)
get_active_char(player)
set_active_char(player, char)
get_next_char(player, char)
context_player()
force_switch_next(player)
register_on_all_hp(op, fn)
register_on_all_energy(op, fn)

-- Target (all deal_damage/heal use these, not HP counter refs)
Target.EnemyActive  Target.EnemyAll  Target.EnemyNonActive
Target.OwnActive    Target.OwnAll    Target.CardTarget

-- Enums
Element.None/Fire/Ice/Water/Electro/Geo/Physical
Tag.Summon/Element/Equip/Food/Support/Shield
Player.Own/Enemy/All
Zone.Hand/Deck
Scope.Self/ActiveStatus/PerChar/PerPlayer/Global
Op.Set/Add/Sub
Source.Skill/Card/Status/Summon/Support/Reaction
Weapon.None/Sword/Polearm/Bow

-- Hooks: on_xxx(fn) or on_xxx(priority, fn)
on_damage_boost  on_reaction_damage  on_damage_reduce  on_after_damage
on_action_check  on_action_prepare  on_skill_use  on_card_play
on_switch  on_before_turn_flip
on_round_start  on_round_end  on_round_end_post_summon  on_round_end_decay  on_round_end_final
on_before_write(counter, op, fn)  on_after_write(counter, op, fn)
```

## Project Layout

```
gicg_engine/
  api.go, game.go, action.go,   — engine core (counters, hooks, players, phases)
  damage.go, hook.go, round.go
  eventlog.go                   — replay-ready event log + state snapshots
  observation.go                — RL observation tensor builder
  interp/                       — DSL parser + AST interpreter
    lexer.go, parser.go, eval.go
    builtins.go                 — declare_counter/get_counter/declare_skill/... + enums
    registry.go                 — counter/char/skill/card registries
    proxies.go                  — counter proxies (Self, PerPlayer, PerChar, Global)
    loader.go                   — ExecFileSandboxed, LoadFilesWithDeps (topo)
    deck.go                     — BuildDeck helper
  record/                       — game record export/parse/replay/verify/load
  capi/                         — c-shared export for Python (libgicg.dylib)
  tests/                        — all Go-side tests (helpers_test.go + per-feature)

data/
  characters/
    赤蝶/ 墨客/ 猫咪/ 刻师傅/ 天星/
  cards/
    L1/ 碌碌无为
    L2/ 美味烧鸡, 佛跳墙, 占星, 诅咒
    L3/ 速速茶点, 铁剑, 铁枪, 荷花酥, 以牙还牙, 反制
    L4/ 铁弓, 西风长枪, 西风剑, 瞬身之术, 伏兵之术, 清洁时间, 玄冰
    L5/ 蝶鳞, 守正, 刺刺猫爪, 发现静电, 星愿
    L6/ 以逸待劳, 乘胜追击, 以攻代守
  system/
    element.lua, frozen.lua, reaction.lua, reactions/
    round.lua, draw.lua, timeout.lua, food.lua, equip.lua
```
