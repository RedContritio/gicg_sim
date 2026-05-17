# ADR-0012: 特技系统 + 准备技能 — DSL/engine 扩展设计

> **MOVED to `openspec/changes/archive/0012-specialty-and-prepare-skill/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0012-specialty-and-prepare-skill/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0012-specialty-and-prepare-skill/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


**Date:** 2026-04-28 PM (accepted 2026-05-07)
**Status:** ACCEPTED — spike 已验证(prepare_skill_spike_test + specialty_spike_test PASS),生产 builtin 落地(set_preparing / draw_card / add_dice / invoke_skill_silent in interp/builtins_adr0012.go);ADR-0019 §A 依赖前置任务(C.1)。
**Drives:** [`docs/3_plans/cards/dsl_gaps.md`](../3_plans/cards/dsl_gaps.md) ★★★ gap C+B
**Spike scope:** 驰轮车·疾驰 + 希诺宁(特技)+ 歼灭特化型机关·高频旋击(准备)

## Context

sqrt(N)=52 张样本扫描发现 5 个 ★★★ DSL gap。本 ADR 聚焦两个最阻塞的:

1. **特技(Specialty)**:玛薇卡时代核心机制(4.x 后半起),装备牌附带子技能,角色级 1 槽,使用算战斗行动但不算技能
2. **准备技能(Prepare Skill)**:歼灭机关 / boss 怪类机制,跨多个行动轮触发,跳过 turn,不触发 on_skill_use 后续

剩余 ★★★ 中 D1(`draw_card`) / D2(`add_dice`) 都是 builtin export,顺路一起做。A1(夜魂)是 DSL 复杂度,无 engine 改,留 DSL 编写阶段。

## Decision

### 1. EventContext 扩展

`engine.EventContext` 加两个 bool:

```go
type EventContext struct {
    ...
    IsSpecialty    bool  // frame 是特技调用 → hook 可 filter
    SkipSkillHooks bool  // silent invoke,不 fire HookSkillUse 后续
}
```

含义:
- `IsSpecialty=true` 时,伤害管道下游 hook(如"角色造成伤害"统计)可检查 `if ctx.IsSpecialty then return end` 跳过
- `SkipSkillHooks=true` 由 silent invoke / prepare resolve 设置,FireEventHooks 内首次检查跳过 on_skill_use chain(但仍跑 skill effect 本身)

### 2. 特技槽 — counter group

新增 `Tag.Specialty`(类似已有 `Tag.Equip` / `Tag.Support`)。装备特技时 `add_card_to_slot(card, Slot.Specialty)` 占 1 槽,引擎层强制 1-card 上限。

`declare_card` 加 `slot` 字段:

```lua
declare_card("驰轮车·疾驰", { dices = { same = 1 } }, {
    slot = Slot.Specialty,
    requires_char = "玛薇卡",
})
```

未指定 `slot` 的卡跟当前一致(Hand → in-game effect → discard)。

### 3. Silent invoke

新 builtin `invoke_skill_silent(skill_id)`:与 `invoke_skill` 同入口,但 push frame 时 `SkipSkillHooks=true`。FireEventHooks(HookSkillUse) 检查 flag → 不 dispatch DSL 注册的 on_skill_use,但仍跑 engine 自带的 skill_use canonical hook(消能量 / 加 dice 等核心管道)。

也可以拆得更细:`SkipDSLSkillHooks`(仅跳过 DSL 注册的)vs `SkipAllSkillHooks`(全跳)。Spike 验证哪个粒度合适。

### 4. 准备技能 — Game 字段 + builtin

`engine.Game` 加 `Preparing [2]int`(准备中 skill id,0=无):

```go
type Game struct {
    ...
    Preparing [2]int  // 0 = 无;>0 = skill_id 待 turn-flip 时触发
}
```

DSL builtin:
- `set_preparing(player, skill_id)` — 进入准备状态
- `get_preparing(player) -> int`
- `clear_preparing(player)` — 显式清(被中断时用)
- `skip_turn(player)` — 跳过下次 turn(配合 preparing 使用)

Turn-flip 拦截:`Game.Step` 在 `before_turn_flip` hook 后检查:
- 若该方 `Preparing[p] != 0`:silent invoke 该 skill(`SkipSkillHooks=true`),清 `Preparing[p]`,**不**翻转给该方
- 否则正常 turn flip

新 hook `HookPrepareResolve`(在 silent invoke 之前 fire,可 cancel — 如冻结时不准备):

```lua
on_prepare_resolve(function(ctx)
    if 角色被冻结 then ctx.Cancelled = true end
end)
```

### 5. 资源 builtin

```lua
draw_card(player, n)        -- 从牌库顶抽 n 张到手牌
add_dice(player, element, n) -- 生成 n 个指定元素骰(Element.Omni 即万能)
```

`draw_card`:engine 已有 `Game.DrawCard(playerIdx)` 内部接口(单张),export 包装多张 + 卡组空时 graceful。

`add_dice`:engine 改 `Game.Players[p].Dice` 添加;考虑 `FixDice` 配置时的交互(spike 验证:fix_dice 是否还应该被生成的覆盖)。

## DSL 改动汇总

| 字段 / builtin | 类型 | 说明 |
|---|---|---|
| `Slot.Specialty` | enum | declare_card 的 slot 选项 |
| `Tag.Specialty` | counter tag | 槽位 counter group |
| `invoke_skill_silent(id)` | builtin | 不触发 on_skill_use 后续 |
| `set_preparing(p, id)` | builtin | 设置准备状态 |
| `get_preparing(p)` | builtin | 查询 |
| `clear_preparing(p)` | builtin | 清准备 |
| `skip_turn(p)` | builtin | 跳过下次 turn |
| `on_prepare_resolve(fn)` | hook | 准备完成时触发 |
| `draw_card(p, n)` | builtin | 抽 n 张 |
| `add_dice(p, element, n)` | builtin | 生成骰 |
| `ctx.IsSpecialty` | ctx field | hook 内可 filter |

## Engine 改动汇总

| 文件 | 改动 |
|---|---|
| `engine/event.go`(或 game.go) | `EventContext` 加 IsSpecialty / SkipSkillHooks;`Game` 加 Preparing[2] |
| `interp/builtins_skill.go` | invoke_skill_silent;set/get/clear_preparing;skip_turn;HookPrepareResolve fire |
| `interp/builtins.go` | 注册新 builtin |
| `interp/builtins_action.go` | turn-flip 拦截 preparing |
| `interp/builtins_card.go` | declare_card 的 slot 字段处理;Slot.Specialty 槽强制 |
| `interp/builtins_dice.go`(新)| add_dice |
| `engine/hooks.go` | HookPrepareResolve 类型 |

## Spike 计划

3 张代表卡端到端验证:

1. **希诺宁**(`character/505321`)— 特技拥有者,夜魂值
   - `declare_char("希诺宁", {hp=12, max_energy=2, element=Element.Geo, weapon=Weapon.Polearm})`
   - 普通攻击 / 元素战技 / 元素爆发 — 标准
   - 装备夜魂状态时累积夜魂,夜魂为 0 时弃刃轮装束(也是新 buff 牌)
2. **驰轮车·疾驰**(`action/505460`)— 特技装备牌
   - `declare_card("驰轮车·疾驰", {dices={same=1}}, {slot=Slot.Specialty, requires_char="玛薇卡"})`
   - 装备时给"玛薇卡"加特技"疾驰"
3. **歼灭特化型机关**(`monster/501447`)— 准备技能
   - 普通攻击产 0 能(unsure 数据)
   - 元素战技"高频旋击":`set_preparing(self, 超速旋击_skill_id)` + `skip_turn(self)`
   - 准备完成 turn:silent invoke 超速旋击,造成 1 点物理 + 此角色额外 1 点充能

Spike 通过判据:
- ✅ Lua 文件能 declare 不报错
- ✅ Game init 后 ruleset 含这 3 个 char/card
- ✅ Mock match 能 invoke 特技 / 准备技能,counter 状态正确演变
- ✅ 单测 + e2e test 通过

Spike 失败判据 → 回 ADR 修设计:
- engine 改动 > 500 行(过度复杂)
- DSL 表达需要新增 5 个以上 builtin(超出预算)
- 端到端 play 行为与 wiki 描述不一致

## Out of scope(留作后续)

- A2 始基力反应(reactions/ 扩展)
- E1 结晶 → 护盾(reactions DSL)
- F ctx.element setter 文档
- H Target 扩展
- 其他 ★★ / ★ gap

## References

- `docs/3_plans/cards/dsl_gaps.md` — 全 gap 列表
- `docs/3_plans/cards/cleansing_schema.md` 领域笔记 § 特技槽
- `data/cleaned/character/505321_希诺宁.yaml` — 特技拥有者样本
- `data/cleaned/action/505460_驰轮车_疾驰.yaml` — 特技装备牌样本
- `data/cleaned/monster/501447_歼灭特化型机关.yaml` — 准备技能样本
- `data/cleaned/_glossary.yaml` 术语 `特技` / `准备技能` 完整解释
