---
last_updated: 2026-06-12
status: LIVE
schema_version: 0
parent: ./spec.md
---

# Hook dispatch — HookType / Priority / 注册顺序 / filter 语义

> 治理 [`./spec.md`](./spec.md) invariant #5 / #6 / #15。
> Hook 是 DSL 与 engine 协作的唯一回调机制。Engine emits typed events
> at well-defined points,DSL hooks 注册回调,通过 `ctx.*` 字段过滤事件
> 并执行 game logic。Engine 不做 filter matching — 所有过滤在 DSL 侧。

## 1. Core 数据模型

Hook 在 engine 内是 flat 数组(`CLAUDE.md "Core Model"` 段):

- **Counter**:flat `[]Counter` array,Value / Init / Min / Max + auto-clamp。
- **Hook**:flat hook array。Dispatched by HookType,ordered by
  Priority(high first,default 0),then registration order。
- **No filter matching in Go**。DSL callbacks SHALL do their own filtering
  (early return on `ctx.*` fields)。
- **Skill ID**:globally unique auto-increment。`ctx.skill_index` SHALL be
  sufficient to identify any skill。

## 2. Hook 注册

### 2.1 Signature

DSL hook 注册 SHALL 采用以下形式之一(详 [`./builtin-api.md`](./builtin-api.md)):

```lua
on_xxx(function(ctx) ... end)               -- default priority 0
on_xxx(priority, function(ctx) ... end)     -- explicit priority(int)
```

### 2.2 Dispatch 顺序

Engine SHALL dispatch hooks in this order:

1. **HookType**:Engine emits 同 type 的事件按以下两层排序:
2. **Priority**:数字越大越先 dispatch(default = 0)。
3. **Registration order**:同 priority 内按 DSL 加载 / 注册时机排序。

注册顺序由 `Runtime.LoadFilesWithDeps` 拓扑序决定 + 同一文件内
顺序执行决定。Mirror match 下 same file 加载两遍,产生两份 hook
(per-binding,详 [`./skill-pattern.md`](./skill-pattern.md))。

## 3. HookType 枚举

Hook types 定义在 `gicg_engine/types.go`。Strict damage ordering 详
[`./damage.md`](./damage.md) §1.1:

### 3.1 Counter 写入

- `HookBeforeWrite` — counter 修改前;可改 `ctx.value`
- `HookAfterWrite` — counter 修改后;read-only

### 3.2 Damage pipeline(strict 8 时机)

详 [`./damage.md`](./damage.md):

- `HookDamageType` — 元素修改(物理→火附魔等)
- `HookDamageAdd` — 加法增伤(班尼特 +2)
- `HookDamageMul` — 乘法增伤(future-proof)
- `HookReactionDamage` — 元素反应
- `HookDamageReduceBuff` — 减伤 buff(物理半伤等)
- `HookShieldAbsorb` — 护盾消耗(详 [`./damage.md`](./damage.md) "Shield" 段)
- `HookDamageImmunity` — 免疫(kill all)
- `HookAfterDamage` — 始终触发

### 3.3 Heal / Energy pipeline

- `HookBeforeHeal` / `HookAfterHeal` — heal 前后;before 可改 value
- `HookBeforeEnergyGain` / `HookAfterEnergyGain`
- `HookBeforeEnergyConsume` / `HookAfterEnergyConsume`

### 3.4 动作系统

- `HookActionCheck` — 动作可用性检查;`ctx.Playable` 默认 true
- `HookActionPrepare` — 动作预处理;可改 Cost / EnergyCost / BattleAction /
  TargetMode
- `HookSkillUse` — 技能效果
- `HookCardPlay` — 卡牌效果
- `HookSwitch` / `on_switch` — 出战角色实际变化事件，包含主动切换、超载等规则强制
  切换和阵亡换人；目标已是出战角色的强制设置不产生事件。
  “进行切换角色操作”专指主动操作，效果消费须在 `on_switch` 中额外检查
  `ctx.action_context == Action.Switch`；强制变化不满足此条件。
  `HookActionPrepare` 可在合法动作查询中执行，只用于准备/费用计算，不用来统计
  已执行的切换次数。该语义区分依据用户2026-09-12确认。
- `HookBeforeTurnFlip` — 行动权翻转前;可修改 BattleAction
- `HookOnTune` — 调和(Tune);ADR-0019 §A.4 / dsl_gaps D3,卡作元素调和使用时

### 3.5 回合阶段

- `HookRoundStart` — 回合开始
- `HookRoundEnd` / `HookRoundEndPostSummon` / `HookRoundEndDecay` /
  `HookRoundEndFinal` — 回合结束多 phase
- `HookBeforeTurnFlip` — 见 3.4

### 3.6 生命周期

由 alive counter 0↔1 跃迁驱动:

- `HookDeath` — alive:1 → 0
- `HookRevive` — alive:0 → 1(包括初始登场)

支援区生命周期:

- `HookSupportRemove` — 支援卡从 `PlayerState.Supports` 移除时;ctx 含
  `ActorPlayer` + `CardRef`

### 3.7 通用兜底

- `HookAction` — 任意动作兜底

## 4. Filter 语义

### 4.1 DSL-side filter,not Go-side

Engine SHALL NOT match hooks by callback signature / 注册时声明的条件。
所有 filter SHALL 在 callback 内通过 `ctx.*` early-return 实现:

```lua
on_skill_use(function(ctx)
  -- filter 1: mirror match owner filter
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then
    return
  end
  -- filter 2: skill identity
  if ctx.skill_index ~= 枪 then return end
  -- effect
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
```

### 4.2 Filter 字段

Hook ctx fields 可用于 filter(详 [`./builtin-api.md`](./builtin-api.md)):

- `ctx.actor_player` / `ctx.actor_char` — who acted
- `ctx.target_player` / `ctx.target_char` — who is affected
- `ctx.skill_index` — `*SkillRef`(SHALL NOT use `.id`)
- `ctx.card_ref` — `*CardRef`(SHALL NOT use `.id`)
- `ctx.source` — `Source.Skill` / `Source.Card` / `Source.Reaction` /
  `Source.Summon` / `Source.Support`
- `ctx.action_context` — switch / skill use / card play / etc.
- `ctx.value` — damage / heal / counter delta value(部分 hook 可改)
- `ctx.element` — damage element(部分 hook 可改)

## 5. Mirror match — per-binding load 与 actor filter

详 [`./skill-pattern.md`](./skill-pattern.md)。简介:

Character DSL files 在 mirror match(same char 两侧)被加载两遍。
每个 owner slot 一份,意味着同一 `on_skill_use` 注册两次。Actor-centric
hooks 必须 filter 到 loading owner:

- `on_skill_use`
- `on_damage_boost`(attacker-side phase)
- `on_card_play`
- attacker-side `on_after_damage`
- `on_action_check` of own candidates

否则 effects 会 double-fire。

PerPlayerHooks events(`on_round_start` / `on_round_end*` /
`on_before_turn_flip`)SHALL be dispatched per-owner automatically — no
actor filter needed。

## 6. Hook owner obs gap — char_skill_refs slot

Hook owner 信息在 Python RL obs 中曾经丢失(commit `3c2ee89` 前),
导致 attention 网络无法定位 char-skill hooks 的 owner slot。修复:engine
在 obs 中加 `char_skill_refs` 区域,由 `Game.Obs.IncludeCharSkillRefs`
toggle 控制(实现见 `gicg_engine/observation.go`)。

Engine SHALL expose `char_skill_refs` slot,SHALL guarantee每个 char-skill
hook 在 obs 中可被定位到其 owner char。

## 7. Actor 事件帧契约(F1)

`deal_damage` / `heal` / `invoke_skill` / `gain_energy` / `consume_energy`
SHALL only be called from hooks dispatched with an actor event frame
(engine 在 dispatch 前 `PushEvent` actor 帧)。事件栈空时引擎 SHALL
panic(`Game.MustCurrentEvent`,fail-loud)— SHALL NOT 静默回退零值帧
(Player=0)以 P0 视角结算(run-150 回合末友伤 bug 的根因)。无帧
dispatch 站点(如 `on_before_turn_flip` / `on_action_check`)的 DSL
callback SHALL NOT 调用上述 builtin。

消费端断言点:`DealDamage` / `Heal` / `GainEnergy` / `ConsumeEnergy`
(`gicg_engine/damage.go`)+ `resolveTargetHP` / `invoke_skill`
(`gicg_engine/interp/`)。契约测试:
`gicg_engine/tests/empty_stack_actor_test.go`。

## 8. Hook 数据来源 cross-reference

- **Engine 数据模型**:`gicg_engine/types.go`(L100+ `HookType` 枚举);
  `gicg_engine/hook.go`(hook 数组 + dispatch 实现)
- **Builtin registration**:`gicg_engine/interp/builtins.go`(`on_*` 系列
  builtin 在 tokenize + eval 两侧注册,详
  [`./builtin-api.md`](./builtin-api.md) §2)
- **ADR-0019**:strict 8 时机 damage pipeline 设计依据见
  [`./damage.md`](./damage.md) §1.1 和
  [`0019-dsl-v6-semantic-engine`](../../changes/archive/0019-dsl-v6-semantic-engine/)
- **Mirror match**:角色绑定与 actor filter 见本文件 §5 和
  [`./skill-pattern.md`](./skill-pattern.md) §3。

## 反应解析完成事件（2026-09-14）

`on_after_reaction` SHALL 在成功反应解析后、主伤害减免与反应附加伤害前触发。
`ctx.reaction_kind` 标识反应，`ctx.reaction_element` 是由DSL设置的关联元素（扩散的被扩散元素）。
纯附着也可产生此反应事件，带 `ctx.attachment_only=true`；它不是伤害事件。
伤害管道中的 `Element.None` 消耗标记 SHALL 不抹去最终伤害元素类型。
