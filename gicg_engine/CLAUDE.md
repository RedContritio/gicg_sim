# CLAUDE.md

## Build & Test

```bash
# from gicg_engine/
go test ./lua/ -v -count=1
go test ./lua/ -run TestE2E_BasicAttack -v -count=1
go build ./...
```

## Architecture

Three-layer: **Lua DSL** (game data) → **Go engine** (generic executor) → **Python** (RL, not yet).

### Engine Ignorance

Go engine knows: characters, hand, deck, round, turn.
Go engine does NOT know: HP, energy, elements, shields, freeze, AP.
All game mechanics = counter + hook in Lua.

### Core Model

- **Counter**: flat `[]Counter` array. Value/Init/Min/Max with auto-clamp.
- **Hook**: flat hook array. Dispatched by HookType, ordered by Priority (high first, default 0), then registration order.
- **No filter matching in Go.** Lua callbacks do their own filtering (early return on ctx fields).
- **Skill ID**: globally unique auto-increment. `ctx.skill_index` is sufficient to identify any skill.

### Counter System

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

### Damage Pipeline

```
① on_damage_boost     — 增伤（附魔、加伤），可修改 value/element
② on_reaction_damage  — 元素反应
③ on_damage_reduce    — 减伤（护盾吸收），可修改 value（仅非穿透）
④ HP write
⑤ on_after_damage     — 始终触发
```

Shields register on `on_damage_reduce` (NOT on_before_write(hp)).

### Dependency Graph

`LoadFilesWithDeps(paths)` in Go:
1. Scans each file for `declare_counter`/`declare_char`/`declare_skill` (provides) and `get_counter`/`get_char`/`get_skill` (depends)
2. Builds dependency graph, topological sort
3. Loads files in sorted order via `DoFileSandboxed`

### File Isolation (setfenv)

DSL files loaded via `DoFileSandboxed` get an isolated env (`__index = _G`).
- Can READ prelude APIs/enums from `_G`
- Writes stay in file-local env
- Cross-file sharing only through `declare_counter`/`get_counter`/`declare_skill`/`get_skill`/`get_char`

## Project Layout

```
gicg_engine/
  prelude/
    counter.lua                — declare_counter/get_counter, get_counter_group, register_on_tag_write
    char.lua                   — declare_char/bind_char/get_char, register_on_all_hp/energy
    skill.lua                  — declare_skill/get_skill, invoke_skill
    card.lua                   — declare_card/get_card, add_card, Target.CardTarget resolution
    damage.lua                 — deal_damage/heal, target resolution, Player constant wrappers
    sandbox.lua                — setfenv sandbox loading
    death.lua                  — register_death_check
  lua/                         — Go↔Lua bridge (cgo)

../data/
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

## DSL Language Subset

### Allowed

`local`, `if`/`elseif`/`return`, `and`/`or`/`not`, comparisons, arithmetic, `function(ctx)...end`, `{key=value}`, `min`/`max`

### Forbidden

`for`/`while`/`repeat`, `pairs`/`ipairs`, `math.*`, `#`, named function definitions, `setmetatable`/`rawset`, `string.*`/`table.*`/`io.*`, global variable writes

### Skill Pattern

```lua
-- 定义技能的文件
local 枪 = declare_skill(赤蝶, "枪", 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 枪 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
```

```lua
-- 引用技能的文件
local 枪 = get_skill(赤蝶, "枪")
```

### Shield Pattern (on_damage_reduce)

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
