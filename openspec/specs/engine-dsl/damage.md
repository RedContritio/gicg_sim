---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
parent: ./spec.md
---

# Damage pipeline — 5-phase flow + on_damage_reduce shields

> 治理 [`./spec.md`](./spec.md) invariant #7 / #8。
> Damage pipeline 是 DSL 与 engine 协作中规则最严的子系统。Engine 提供
> 5 个 dispatch 点(strict 8 时机 in ADR-0019 §B.5 内部),DSL hooks
> 在其中修改 value / element / 吸收伤害。Phase 顺序 SHALL 不可重排。

## 1. Pipeline 5-phase flow

伤害事件 SHALL 按以下顺序经过 5 个 phase:

```
① on_damage_boost      — 增伤(附魔、加伤),可修改 value/element(仅非穿透)
② on_reaction_damage   — 元素反应(仅非穿透)
③ on_damage_reduce     — 减伤(护盾吸收),可修改 value(仅非穿透)
④ HP write             — engine 写入 HP counter
⑤ on_after_damage      — 始终触发(read-only,衍生效果)
```

每个 phase SHALL 按 [`./hook.md`](./hook.md) "Dispatch 顺序" 规则
(HookType → Priority → registration order)dispatch hook 队列。

### 1.1 ADR-0019 §B.5 strict 8 时机内部分解

`on_damage_boost` 在 engine 内部细分为 3 个 strict 时机
(详 `memory project_adr_0019_strict`):

```
HookDamageType   → ①a 元素修改(物理→火附魔等)
HookDamageAdd    → ①b 加法增伤(班尼特 +2)
HookDamageMul    → ①c 乘法增伤(future-proof)
```

`on_damage_reduce` 在 engine 内部细分为 3 个 strict 时机:

```
HookDamageReduceBuff → ③a 减伤 buff(物理半伤等)
HookShieldAbsorb     → ③b 护盾消耗
HookDamageImmunity   → ③c 免疫(kill all)
```

DSL 作者面 SHALL 通过统一的 `on_damage_boost` / `on_damage_reduce`
注册接入,engine 内部 dispatch 自动落到对应 strict 时机。Strict 8 时机
枚举详 [`./hook.md`](./hook.md) §3.2。

## 2. Phase 1 — on_damage_boost(增伤)

### 2.1 可修改字段

- `ctx.value` — damage value(integer,SHALL ≥ 0)
- `ctx.element` — damage element(`Element.None` / `Fire` / `Ice` / `Water` /
  `Electro` / `Geo` / `Physical`)— 附魔 / 化伤等

### 2.2 Filter 字段

- `ctx.actor_player` / `ctx.actor_char` — attacker
- `ctx.target_player` / `ctx.target_char` — defender
- `ctx.source` — `Source.Skill` / `Source.Card` / `Source.Reaction` /
  `Source.Summon` / `Source.Support`
- `ctx.skill_index` / `ctx.card_ref` — invocation identity(SHALL use ref,
  not int ID)

### 2.3 Actor-side filter required

Attacker-side `on_damage_boost` hook 在 mirror match 下 SHALL filter to
loading owner(via `ctx.actor_player` / `ctx.actor_char`),否则双注册
导致双倍增伤(详 [`./skill-pattern.md`](./skill-pattern.md))。

## 3. Phase 2 — on_reaction_damage(元素反应)

### 3.1 Reaction 表

Engine SHALL dispatch reaction hooks when attack element + existing element
attachment 产生反应。Reaction 表实现在 `data/system/reaction.lua` +
`data/system/reactions/`(详 `docs/1_specs/engine/dsl/conventions.md`
"Project Layout" 段)。

### 3.2 Reaction value / element 修改

Reaction hooks 可以 read `ctx.element`(攻击元素)+ `ctx.target_element`
(被附着元素),emit 额外 damage / status changes。SHALL NOT 直接改
`ctx.value` — reactions 通过 `deal_damage` 添加 secondary damage event,
保持 phase ordering 清晰。

## 4. Phase 3 — on_damage_reduce(减伤)

### 4.1 可修改字段

- `ctx.value` — damage value(SHALL ≥ 0,clamp 后写 HP)
- SHALL NOT 修改 `ctx.element`(已 final)
- SHALL NOT 影响穿透伤害(`Element.Piercing`)。

穿透伤害 SHALL 跳过元素修改、加法/乘法增伤、元素反应、减伤 buff、
护盾吸收和免伤 hook；因此 SHALL NOT 消耗这些效果的次数或护盾值。
穿透伤害仍 SHALL 扣除 HP，处理死亡并触发 `on_after_damage`。
这些规则对双方、出战和后台角色均适用。

### 4.2 Shield 注册位置约束

Shields SHALL register on `on_damage_reduce` phase(NOT
`on_before_write(hp)`)。原因:`on_damage_reduce` 在 reaction 后 / HP write
前,既可见反应后的最终 value,又可在 HP 写入前吸收。在
`on_before_write(hp)` 注册会错过 reaction 修正 + 顺序混乱。

### 4.3 Defender-side filter required

Shield owner 必须按 `ctx.target_player` / `ctx.target_char` filter,避免
吸收他人伤害:

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

### 4.4 Shield counter tag

Shield counters SHOULD declare `tag=Tag.Shield`,便于 group 操作 +
inspector 工具识别:

```lua
local 猫爪护盾 = declare_counter("猫爪护盾", Scope.Self, 0,
  {min=0, max=3, tag=Tag.Shield})
```

## 5. Phase 4 — HP write

Engine SHALL write `ctx.value` to HP counter via standard counter mutation
path(triggers `on_before_write(hp)` / `on_after_write(hp)` for HP counter
hooks,详 [`./counter.md`](./counter.md) "Counter callbacks & write hooks"
段)。

HP write SHALL clamp at HP counter min(通常 0)。当 HP 跌至 0,alive
counter 自动 0↔1 transition,触发 `HookDeath`(详
[`./hook.md`](./hook.md) §3.6)。

## 6. Phase 5 — on_after_damage(始终触发)

### 6.1 Read-only

`on_after_damage` SHALL be read-only — SHALL NOT 修改 `ctx.value`
(已写入)。常用于:

- 衍生效果(damage 后 trigger 计数 / 召唤物 expire / 元素清除)
- Buff stacking(每次受伤加一层防御 buff)
- 死亡 trigger(虽然 `HookDeath` 更精确,部分场景需 attack-source 信息)

### 6.2 Always fires

`on_after_damage` SHALL fire 即使 `ctx.value` 被 reduce 到 0(完全吸收),
即使 target 已死亡。Filter SHALL 自己判断 `ctx.value == 0` / `target:alive()`。

### 6.3 Actor / target dual side

`on_after_damage` 同时 dispatch attacker-side + defender-side hooks。两侧
都注册时 SHALL filter:

- Attacker-side:`ctx.actor_player` / `ctx.actor_char`(mirror filter)
- Defender-side:`ctx.target_player` / `ctx.target_char`

## 7. Shield Pattern — canonical exemplar

```lua
-- 猫爪护盾(简化版):每次受到伤害,先吸收 shield 值
local 猫咪 = get_char("猫咪")
local 猫爪护盾 = declare_counter("猫爪护盾", Scope.Self, 0,
  {min=0, max=3, tag=Tag.Shield})

on_damage_reduce(function(ctx)
  -- defender filter
  if ctx.target_player ~= 猫咪:owner_player() then return end
  if ctx.target_char ~= 猫咪:owner_char() then return end
  -- shield gate
  local shield = 猫爪护盾:get()
  if shield <= 0 then return end
  -- absorb
  local absorb = min(shield, ctx.value)
  猫爪护盾:sub(absorb)
  ctx.value = ctx.value - absorb
end)
```

更完整 exemplar 详 `memory reference_dsl_example`(以牙还牙):summon
lifecycle + damage 反伤 + counter cleanup 的端到端示例。

## 8. E2E 验证场景

Engine + DSL 必须维持的端到端 invariant(详
`memory project_e2e_test_scenario` 赤蝶泼墨蒸发):

- 多 buff 叠加顺序(`on_damage_boost` 排序确定)
- Reaction 触发 secondary damage(蒸发 / 融化等)
- Filter 在多个 phase 内一致(同 target_char 在所有 phase 看到一致值)
- Shield 吸收后,后续 phase `ctx.value` SHALL 已更新

Engine + DSL 之间任何 phase ordering 调整 SHALL 走 OpenSpec change,
SHALL 跑该场景 e2e 测试通过后才允许合入。

## 9. Cross-reference

- HookType 枚举详 [`./hook.md`](./hook.md) §3.2
- Counter API(`get` / `set` / `add` / `sub` / `cmin` / `cmax`)详
  [`./counter.md`](./counter.md) §2 + [`./builtin-api.md`](./builtin-api.md)
- Skill / card identity(`*SkillRef` / `*CardRef`)详
  [`./skill-pattern.md`](./skill-pattern.md) + `memory feedback_ctx_skill_index_type`
- ADR-0019 strict 8 时机:`memory project_adr_0019_strict`
- 反应表实现:`data/system/reaction.lua` + `data/system/reactions/`
