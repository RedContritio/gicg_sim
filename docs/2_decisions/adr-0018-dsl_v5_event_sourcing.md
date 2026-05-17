---
adr: 0018
title: DSL v5 — Event-sourcing 替代 substate 私有 state + ctx 减重
status: PROPOSED (尚未 prototype, 跟 v4 prototype 部分推翻)
date: 2026-05-01
supersedes-partial:
  - adr-0017-dsl_v4.md (A20 substate first-class / A26 multi-instance substate / A28 hierarchical obs / 部分 A18 PDR via substate)
keeps:
  - adr-0017-dsl_v4.md (A1-A17 / A19 / A21-A25 / A27 / A29-A31 全保留)
---

# ADR-0018: DSL v5 — Event-sourcing

> **MOVED to `openspec/changes/archive/0018-dsl-v5-event-sourcing/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0018-dsl-v5-event-sourcing/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0018-dsl-v5-event-sourcing/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


## Status

PROPOSED — 基于 v4 prototype (gicg_engine/v2/) opus subagent 评审 + user 设计反馈触发的根本性重构。**改动范围涉及 v4 prototype 大头**, 进入 prototype 重构前需 user 确认本 ADR。

## Context — v4 prototype 暴露的两个根本问题

### 问题 1: substate 抽象过度设计

v4 prototype `gicg_engine/v2/substate.go` 引入 `SubstateInstance.Scalars/Collections + LegalActions/OnAction + Recycle pool`, 假设 RL 在 substate 内可能多步交互 (选 1 → 看 → 选 1 → 看 → 选 1)。但 GICG 实际场景全部是 **one-shot decision**:

| 场景 | "看似多步" → 实际 |
|---|---|
| 千织 3-of-4 召唤物挑选 | RL 一次返回 `SelectedIndices=[0,2,3]` (3 个 idx),不是分 3 step |
| 勘探钻机 BinaryChoice | RL 一次返回 `ChosenBinary=1`,不分 2 step |
| 烈絮 sub-skill 选 | RL 一次返回 `ChosenSkillIdx=2`,不分 N step |
| Cost payment | RL 一次返回 `PaidDice=[Fire,Fire,Anemo]`,不分 N step |
| 投骰子 → 看 → 重投 | 这其实是**两个独立 game step** (engine random 在中间), 不是 substate 内多步 |

→ `SubstateInstance.Scalars / LegalActions / OnAction / Recycle pool` **无真实需求**, 是过度设计。

### 问题 2: ctx 太重 + transient 不进 obs

v4 `Ctx` 持 `Proposals / NestedSubActions / HoldFor / DecisionResult / Provenance` 等 transient state, hook 间通信用。但 transient = commit 后就消失, **不进 obs**。这导致 opus subagent 评审找出 3 个 P0 漏洞:

- **P0-2**: PDR sync hold 时 RL 看不到 in-flight ctx (勘探钻机受伤 dmg 量丢失, RL 无法 informed 选弃哪张)
- **P0-3**: PropMarker commit noop 不进 LastTransitions (蒸发/融化/扩散 反应类型 RL 黑盒)
- (P0-1 由问题 1 自动消解)

→ ctx + LastTransitions ring 是混合设计 (ctx 写 transient + ring 写 commit summary), 信息有损丢失。

## Decision — 事件系统 + substate 折叠

### 1. 替换 LastTransitions ring → typed Event log (event-sourcing)

```go
// engine/v2/event.go (新)

type EventKind int

const (
    EvSubActionStart    EventKind = iota // SubAction propose 前
    EvProposalAdded                       // 某 hook propose 一个 proposal
    EvProposalRejected                    // resolve hook reject
    EvSubActionCommit                     // commit 成功
    EvSubActionRollback                   // commit 失败
    EvReactionTriggered                   // typed marker 已 propose
    EvDecisionRequested                   // PDR (含完整 in-flight ctx snapshot)
    EvDecisionResolved                    // RL 选完
    EvContainerDestroyed                  // A16 tombstone
    EvActionStart                         // Action 入口 (玩家选 use_skill 等)
    EvActionEnd                           // Action 完成
)

type Event struct {
    ID       int       // 全局递增 unique
    StepID   int       // 哪个 game step (跨 RL step 累计)
    ParentID int       // 反应链 trace: nested event 的父 event id;0 表无父

    Kind EventKind

    // SubAction / Action 共通字段 (按 Kind 互斥)
    SubAction     SubActionKind  // EvSubAction*
    Action        ActionKind     // EvAction*
    Element       ElementType
    TriggerSource TriggerSource
    Actor, Target Owner
    Value         int

    // Proposal snapshot (Kind == EvProposalAdded / Rejected)
    ProposalKind ProposalKind
    ContainerRef ContainerID    // typed id (declared 时 engine 分配),取代 ptr 进 obs
    Delta        int
    NewValue     int
    HookName     string

    // Reaction (Kind == EvReactionTriggered)
    ReactionKind ReactionType  // 蒸发/融化/超载/超导/感电/绽放/激化/结晶/碎冰/扩散
    Marker       *MarkerRef

    // PDR (Kind == EvDecisionRequested)
    Decision         *DecisionSpec
    InFlightSnapshot *SubActionSnapshot  // 解 P0-2

    // PDR (Kind == EvDecisionResolved)
    Result *DecisionResult

    // Commit (Kind == EvSubActionCommit/Rollback)
    CommitCount int
}

// SubActionSnapshot — PDR step 时 RL 看到的 in-flight 当前 ctx 状态。
// 解 P0-2: 勘探钻机弃牌时 RL 知道"我面对 dmg=3 from p0c0 火元素"。
type SubActionSnapshot struct {
    SubAction     SubActionKind
    Element       ElementType
    TriggerSource TriggerSource
    Actor, Target Owner
    Value         int
    // 已 propose 的累计 delta per container (容器 id → delta)
    // 例: hp_p1c0 → -3 (主 dmg 已 propose)
    AccumulatedDelta map[ContainerID]int
    // 已 propose 的 markers (反应类型, RL 看到 vaporize 已 propose)
    Markers []*MarkerRef
}

// ContainerID — declared 时 engine 分配 (取代 string name 字段进 obs / event)。
// Scalar / Collection 加 ID ContainerID 字段, NewGame.DeclareScalar/Collection 自增。
type ContainerID int

// ReactionType — typed 反应分类 (取代 marker name 字符串)。
type ReactionType int

const (
    ReactionNone     ReactionType = iota
    ReactionVaporize              // 蒸发 (火+水 / 水+火)
    ReactionMelt                  // 融化 (火+冰 / 冰+火)
    ReactionOverload              // 超载 (火+雷 / 雷+火)
    ReactionSuperconduct          // 超导 (冰+雷 / 雷+冰)
    ReactionElectroCharged        // 感电 (水+雷 / 雷+水)
    ReactionBloom                 // 绽放 (水+草)
    ReactionQuicken               // 激化 (草+雷)
    ReactionCrystallize           // 结晶 (岩+任一)
    ReactionFrozen                // 碎冰 (水+冰)
    ReactionSwirl                 // 扩散 (风+任一)
    ReactionBurning               // 燃烧 (火+草)
    ReactionHyperbloom            // 超绽放 (绽放+雷)
    ReactionBurgeon               // 烈绽放 (绽放+火)
)
```

### 2. Game.Events ring (替代 LastTransitions)

```go
// container.go
type Game struct {
    // ...原有字段...
    Events    []Event       // bounded ring (replace LastTransitions)
    NextEventID int          // 全局事件 id 自增
}

const MaxEvents = 64  // 16 太小 (反应链密集回合溢出),提到 64

func (g *Game) EmitEvent(e Event) *Event {
    e.ID = g.NextEventID
    g.NextEventID++
    g.Events = append(g.Events, e)
    if len(g.Events) > MaxEvents {
        g.Events = g.Events[1:]  // drop oldest
    }
    return &g.Events[len(g.Events)-1]
}
```

### 3. ctx 减重 (只保留 hook 间临时通信)

```go
// transaction.go
type Ctx struct {
    Game *Game

    // SubAction meta (input, hook 内只读)
    SubAction     SubActionKind
    Element       ElementType
    TriggerSource TriggerSource
    Actor, Target Owner
    Value         int

    // hook 收集 — commit 后销毁, 不持久化 (events 是真持久化)
    Proposals []*Proposal

    // PDR
    HoldFor *DecisionSpec
    DecisionResult *DecisionResult

    // 嵌套 — drain 后销毁
    NestedSubActions []*Ctx

    // 父 ctx (反应链 trace, 但 trace 通过 events 持久化, ctx.Parent 仅 hook 内便利)
    Parent *Ctx

    // 当前 SubAction 对应的 EvSubActionStart event id (用于子 event 的 ParentID)
    EventID int
}
```

**移除的字段**: `Provenance` (改通过 events 串 ParentID), `PendingDecisions` (改通过 events EvDecisionRequested), `Cancelled` (改通过 EvSubActionRollback)。

### 4. substate 整体折叠 → DecisionSpec 扩张

**砍掉**:
- `gicg_engine/v2/substate.go` 整文件 (~213 LOC)
- `SubstateInstance / SubstateTemplate / SubstateRegistry / SubstateField / SubstateAction / SubstateActionKind / SubstateInitData / SubstateExitData`
- `DecisionEnterSubstate` kind

**DecisionSpec / DecisionResult 扩** (`pdr.go` 修改):

```go
type DecisionKind int

const (
    DecisionSelectFromCollection DecisionKind = iota // 千织 (count >= 1)
    DecisionBinaryChoice                              // 勘探钻机
    DecisionTargetChar                                // 普攻指定目标
    DecisionCostPayment                               // A24 dice 支付
    DecisionSelectSkill                               // 烈絮 sub-skill
    DecisionRerollDice                                // 重投选择 (one-shot, 选要重投的 dice indices)
)

type DecisionSpec struct {
    Kind DecisionKind

    // SelectFromCollection / SelectSkill (千织 count=3, 烈絮 count=1)
    SourceCollection *Collection
    SourceItems      []Item   // 当 source 不是 game-level collection 时 (substate 临时候选)
    SelectCount      int      // 选几个

    // BinaryChoice
    Options [2]*BinaryOption

    // TargetChar
    AllowedTargets []Owner

    // CostPayment
    CostSpec *CostSpec

    // RerollDice
    RerollableDice DicePool  // 可重投的 dice (RL 选 indices subset)
}

type DecisionResult struct {
    Kind DecisionKind

    SelectedIndices []int       // SelectFromCollection / SelectSkill / RerollDice — 一次性多 idx
    ChosenBinary    int         // BinaryChoice
    ChosenTarget    Owner       // TargetChar
    PaidDice        []DiceColor // CostPayment
}
```

→ 千织 3-of-4: `Spec{Kind:Select, Source:candidates, Count:3} → Result.SelectedIndices=[0,2,3]` 一次完成。

### 5. obs.RecentEvents (替代 LastTransitions)

```go
// obs.go
type ObsSnapshot struct {
    // ...base game state (Scalars/Collections masked)...
    RecentEvents     []Event        // typed 完整事件链, RL 推理因果
    PendingDecision  *DecisionSpec  // 当前 PDR 决策 spec
    InFlightSnapshot *SubActionSnapshot // 当前 PDR 关联的 in-flight ctx 摘要 (解 P0-2)
}
```

### 6. v4 axiom 影响

| Axiom | 状态 | 备注 |
|---|---|---|
| A1-A17 | 保留 | 容器 / 事务 / hook lifecycle / form / hidden / provenance 全部不变 |
| A18 PDR via substate | **简化** | 从"通过 substate 实现 PDR" → "PDR = DecisionSpec one-shot, 无 substate"。substate 抽象砍掉 |
| A19 plain_key_fn | 保留 | typed dispatch 不变 |
| A20 substate first-class | **OBSOLETE** | 砍掉 |
| A21 provenance | **简化** | 从 ctx.Provenance 32 entry → events ParentID 链 (跨 commit 持久化, 进 obs) |
| A22 TriggerSource | 保留 + 进 events | events 自带 TriggerSource 字段 |
| A23 stdlib whitelist | 保留 | Lua 范围,不变 |
| A24 cost payment | 保留 + 简化 | DecisionCostPayment 直接表达, 不需要 cost_payment substate 实例 |
| A25-async PDR | **简化** | events EvDecisionRequested 替代 PendingDecisions queue |
| A26 multi-instance substate | **OBSOLETE** | 砍掉 (one-shot 无 instance 概念) |
| A27 instance lifecycle | 保留 | card/summon item_ownership 不变 |
| A28 hierarchical obs | **简化** | 改成 "base + RecentEvents + PendingDecision" (无 substate 层, 但 events 替代覆盖更广) |
| A29 attached entity | 保留 | active_in_form + attached_to_char 不变 |
| A30 PDR-sync-with-hold | 保留 + 进 events | EvDecisionRequested + EvDecisionResolved 链, HeldCtx 仍持 in-flight ctx (不进 obs, InFlightSnapshot 才进 obs) |
| A31 L3 obs typed transition log | **替代** | events ring 是更通用的 transition log, A31 整合到 event-sourcing |
| **A32** (新) **Event-sourcing first-class** | NEW | 所有 SubAction / Action / proposal / reject / commit / rollback / decision / destroy / reaction 全部 typed Event, ring bounded N=64, 进 obs RecentEvents。RL 通过 events 序列推理所有规则 (因果 / 反应类型 / 反应链层级 / PDR in-flight) |

axiom 数: 31 → 30 (删 A20 + A26, 加 A32)。

## Migration — 5 step 渐进重构 (gicg_engine/v2/)

每 step 独立 commit + test PASS, 跨 step 时部分 test 阶段性 broken (允许)。

| step | 内容 | 增 LOC | 删 LOC | 测试影响 |
|---|---|---|---|---|
| 1 | event.go: Event/EventKind/SubActionSnapshot/ContainerRef/ReactionType + Game.Events ring (与 LastTransitions 并存, 新代码先用 events) | +200 | 0 | 现有 test 全 PASS |
| 2 | engine SubAction / Action 入口 / commit / rollback / nested 写 events;LastTransitions 移除 | +120 | -60 | TransitionEntry 测试 → Event 测试 (~50 LOC 改造) |
| 3 | substate 整套删 + DecisionSpec 扩 (千织 SelectIndices count / 烈絮 / cost payment 完整 union) | +80 | -300 | substate test 删 + 千织 test 改 one-shot |
| 4 | obs.go RecentEvents 替代 LastTransitions + InFlightSnapshot 进 PDR step obs (解 P0-2) | +60 | -20 | obs test 改 (~30 LOC) |
| 5 | reaction marker → ReactionType enum 进 events (解 P0-3); ADR-0018 标 ACCEPTED + ADR-0017-v4 rename .v4-superseded | +20 ADR | -20 ADR | reaction chain test 加 ReactionType 断言 |

净 ~+480 / -400, 净 +80 LOC (但删掉 substate 抽象后整体清晰度 ↑)。

## Tradeoffs

### 收益
- 解 P0-1/P0-2/P0-3 三个 RL 可观测性漏洞 — RL 可从 obs.Events 唯一推理所有 game rule (含反应类型 / 反应链层级 / PDR in-flight)
- 砍掉 substate 抽象 → 减 ~300 LOC + 概念简化 (没"私有跨步 state" 这种 misnomer)
- ctx 减重 → hook 作者代码更清晰 (transient vs persistent 边界明确)
- 事件 typed first-class → 调试 / replay / analytics 全部受益

### 代价
- prototype 大改造 (重构 ~480 LOC)
- DecisionSpec union 字段扩张 (5 种 → 6 种, 每种多 1-2 typed field)
- ContainerID 引入 (Scalar/Collection 加 ID 字段, declare 时分配 + obs/event 引用 id 而不是 ptr)
- Event ring N=64 vs 当前 16 — 内存 4x (每 Event ~120 byte * 64 = 7.5KB per game),Clone 成本同比上升

### 不做的事 (开放问题, 后续 ADR)
- Event ring N=64 是否够覆盖最长反应链 + sleep round (open question, 需 prototype 实测)
- ReactionType enum 13 类是否覆盖原神所有反应 (含未来出的) — 开放,加新反应改 enum
- DecisionSpec union 字段越扩越多, 是否考虑 sum type per Kind 拆 struct (Go 没真 sum, prototype 阶段 union struct 已够,生产可考虑 codegen)

## Open Questions (动手前需 user 决策)

1. **ContainerID 形态**: `int` (declare 时自增) 还是 `string` (容器 name)?
   - int: typed 严格, obs encode 简单 (固定 slot), 但调试时 RL 看到 "container_id=42" 不直观
   - string: 调试友好但 user 之前明确"不要字符串"
   - **建议**: int, ContainerID typed 类型, debug 时用 Scalar.Name 反查
2. **Event ring N**: 16 → 64 够吗? 还是 128? prototype 测最长反应链 + 计算溢出概率
   - **建议**: 默认 64, 后续可调
3. **substate 砍掉后 v4 prototype 26 个 substate-related test 怎么处理**?
   - 方案 a: 千织/烈絮 test 改 DecisionSpec one-shot (保留覆盖)
   - 方案 b: substate.go + v2_substate_test.go 整删
   - **建议**: a (千织/烈絮 改成 PDR one-shot test 验证 DecisionSpec 扩张正确)

## 进入 Phase 0 之前

ADR-0018 ACCEPTED + 5 step prototype 重构完 + 全 28+ test PASS (含新 reaction type / in-flight snapshot test) → 才能正式启动 v1 → v5 真迁移 (engine 重写 + system DSL 重写 + RL pipeline cgo schema 改)。

跟 ADR-0017 v4 关系: v4 prototype 落地的 typed schema (Item / 10 enum / DecisionSpec / Owner / HiddenFrom / form-bound hook / A16 tombstone / A2-rev group reject / A24 cost auto-resolve) 全部保留, **本 ADR 只动 substate + ctx + transition log 三处**。
