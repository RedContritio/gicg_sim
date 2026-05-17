> **MOVED to `openspec/specs/engine-dsl/`**(2026-05-15,P1-T5)
>
> 本文档内容已迁到 OpenSpec(SHALL 语言):
> - [Spec](../../../../openspec/specs/engine-dsl/spec.md)
> - [Builtin API](../../../../openspec/specs/engine-dsl/builtin-api.md)
>   — Lua subset / builtin function 列表 / actions / targets / enums
> - 详 Subtopics index
>
> 本文件保留至 P1++;**只读**。

---

# DSL 预加载 API

> **Canonical source:** the top-level `CLAUDE.md` "API" block is the
> authoritative list of shipped DSL functions and enums. This file is
> a short companion that explains *how* to use the API; anything that
> looks like a missing/extra function here means CLAUDE.md drifted and
> should be resolved in its favor.

## Execution model

DSL files run in a **sandboxed environment** whose parent is the
pre-populated globals table (see `gicg_engine/interp/builtins.go`
`RegisterBuiltins`). Sandbox rules:

- **Allowed:** `local` declarations, `if`/`elseif`/`return`, `and`/`or`/`not`,
  comparisons, arithmetic, `function(ctx) ... end`, `{key=value}` tables,
  `min`/`max`.
- **Forbidden:** `for`/`while`/`repeat`, `pairs`/`ipairs`, `math.*`,
  `#` length operator, named function definitions, `setmetatable`/`rawset`,
  `string.*`/`table.*`/`io.*`, global variable writes.

Cross-file sharing goes through `declare_*` / `get_*` — never through
globals.

## Declare vs Get

Every DSL entity (counter / char / skill / card) uses the same
declare-or-get pattern:

| Function | Behavior |
|----------|----------|
| `declare_counter(name, scope, init [, {min, max, tag}])` | Create the counter, or return the existing one if `(scope, key, min, max)` match. Mismatched re-declarations raise an error. |
| `get_counter(name, scope [, Player.Enemy])` | Return the existing counter, or raise `unresolved_dependency:name`. Optional second argument binds a `Player.*` constant for the returned proxy. |
| `declare_char(name, {hp, max_energy, element, weapon})` | Same idempotent-create-or-get for chars. |
| `bind_char(name, player_idx, char_idx)` | Wire a declared char into a specific slot. Called by the C API init path per-binding. |
| `declare_skill(char, name, ap [, energy [, opts]])` | Declare a skill on a char. Slot-aware — attaches to `CurrentOwnerPlayer/Char`'s slot via `AddSkill`. |
| `get_skill(char, name)` → `SkillRef` | Returns by char reference. |
| `declare_card(name, ap [, {target, battle_action, requires_weapon, requires_char}])` | Global per-card declaration. Produces a single shared card ref regardless of mirror matches. |
| `get_card(name)` → `CardRef` | |
| `add_card(card_ref, zone [, player])` | Inject a card into `Zone.Hand` / `Zone.Deck`. Used by e.g. `复刻`. |

## Counter scopes and proxies

See `../README.md` §2 and `gicg_engine/interp/proxies.go` for
the shipped proxy types. The four scopes are:

| Scope | Expansion | Key | Typical access |
|-------|-----------|-----|----------------|
| `Scope.Self` / `Scope.ActiveStatus` | 1 counter per (player, char) | `"P:C:name"` | `:get()`, `:set(v)`, `:cmin()`, `:cmax()` |
| `Scope.PerPlayer` | 2 counters | `"name"` | `:get_at(p)`, `:set_at(p, v)`, `:get()` (implicit ctx player) |
| `Scope.PerChar` | 2 × `MaxChars` counters | `"name"` | `:get_at(p, c)`, `:set_at(p, c, v)`, `:decay_all(p)`, `:fill_all(p, v)` |
| `Scope.Global` | 1 counter | `"name"` | `:get()`, `:set(v)` |

`Player.Own` / `Player.Enemy` / `Player.All` are dynamic resolved via
`_current_context_player`. Used in `PerPlayer`/`PerChar` `_at` calls.

Counter groups (`Tag.Summon`, `Tag.Element`, `Tag.Equip`, `Tag.Food`,
`Tag.Support`, `Tag.Shield`) are queryable via `get_counter_group(tag)`
and its `:get()`/`:set(v)`/`:add(v)`/`:sub(v)` methods, with optional
`{player=Player.Own|Enemy|All}` filters.

## Hooks

Full list of supported hook names in CLAUDE.md "API" block. Calling
convention:

```lua
on_xxx(function(ctx) ... end)           -- default priority 0
on_xxx(1000, function(ctx) ... end)     -- high priority runs first
```

Filtering is by **early return inside the callback**, never by filter
tables passed to the hook. The `ctx` argument carries at minimum
`ActionCtx`, `Source`, `ActorPlayer`, `ActorChar`, and hook-specific
fields (`CounterID`/`Op`/`Before`/`After` for write hooks,
`SkillIndex`/`CardRef` for skill/card hooks, `Value`/`Element`/`Hit`
for damage pipeline hooks). See `gicg_engine/interp/builtins.go`
`registerHook` for the stamped `Source`/`CurrentSourceFile` metadata.

## Actions and side effects

| Function | Semantics |
|----------|-----------|
| `deal_damage(target, element, value [, opts])` | Enters the damage pipeline (HookDamageBoost → HookReactionDamage → HookDamageReduce → HP write → HookAfterDamage). `opts = {penetrate, source}` override inherited event frame fields. |
| `heal(target, value)` | Symmetric with damage. Uses `HookBeforeHeal` / `HookAfterHeal`. |
| `invoke_skill(skill_id)` | Re-enters `HookSkillUse` with the current frame's `Source` inherited (e.g. 刻印 invoked by 复刻 keeps `SrcCard`). `Paid=true` skips cost deduction. |
| `defer_fn(fn)` | Append a callback to the current event layer's deferred queue. Executed after the current hook returns but before the layer is popped. |
| `set_active_char(player, char)`, `force_switch_next(player)`, `get_active_char(player)`, `get_next_char(player, char)` | Active-char bookkeeping. `context_player()` returns the frame's current context player. |
| `register_on_all_hp(op, fn)`, `register_on_all_energy(op, fn)` | Shorthands that register write hooks on every known HP/energy counter — used by system files to implement global HP/energy contracts. |

## Targets and enums

`Target.EnemyActive`, `Target.EnemyAll`, `Target.EnemyNonActive`,
`Target.OwnActive`, `Target.OwnAll`, `Target.CardTarget` — all used by
`deal_damage` / `heal`. Element / Weapon / Source / Tag / Zone
constants are listed in CLAUDE.md's "API" block; there is no
`PerOwnChar` or `PerEnemyChar` scope.
