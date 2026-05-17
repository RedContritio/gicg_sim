# Design (retrospective)

## Consequences

### v4 axiom 影响

| Axiom | 状态 | 备注 |
|---|---|---|
| A1-A17 | 保留 | 容器 / 事务 / hook lifecycle / form / hidden / provenance 全部不变 |
| A18 PDR via substate | 简化 | 从"通过 substate 实现 PDR"→ "PDR = DecisionSpec one-shot,无 substate" |
| A19 plain_key_fn | 保留 | typed dispatch 不变 |
| A20 substate first-class | **OBSOLETE** | 砍掉 |
| A21 provenance | 简化 | 从 ctx.Provenance 32 entry → events ParentID 链(跨 commit 持久化,进 obs) |
| A22 TriggerSource | 保留 + 进 events | events 自带 TriggerSource 字段 |
| A23 stdlib whitelist | 保留 | Lua 范围,不变 |
| A24 cost payment | 保留 + 简化 | DecisionCostPayment 直接表达,不需 cost_payment substate 实例 |
| A25-async PDR | 简化 | events EvDecisionRequested 替代 PendingDecisions queue |
| A26 multi-instance substate | **OBSOLETE** | 砍掉(one-shot 无 instance 概念) |
| A27 instance lifecycle | 保留 | card/summon item_ownership 不变 |
| A28 hierarchical obs | 简化 | 改 "base + RecentEvents + PendingDecision"(无 substate 层) |
| A29 attached entity | 保留 | active_in_form + attached_to_char 不变 |
| A30 PDR-sync-with-hold | 保留 + 进 events | EvDecisionRequested + EvDecisionResolved 链,HeldCtx 仍持 in-flight ctx(不进 obs,InFlightSnapshot 才进 obs) |
| A31 L3 obs typed transition log | **替代** | events ring 是更通用的 transition log,A31 整合到 event-sourcing |
| **A32 Event-sourcing first-class** | NEW | 所有 SubAction/Action/proposal/reject/commit/rollback/decision/destroy/reaction 全部 typed Event,ring bounded N=64,进 obs RecentEvents。RL 通过 events 序列推理所有规则 |

axiom 数 31 → 30。

### Migration — 5 step 渐进重构 (gicg_engine/v2/)

| step | 内容 | +LOC | -LOC |
|---|---|---|---|
| 1 | event.go: Event/EventKind/SubActionSnapshot/ContainerRef/ReactionType + Game.Events ring(与 LastTransitions 并存) | +200 | 0 |
| 2 | engine SubAction / Action 入口 / commit / rollback / nested 写 events;LastTransitions 移除 | +120 | -60 |
| 3 | substate 整套删 + DecisionSpec 扩(千织 SelectIndices count / 烈絮 / cost payment 完整 union) | +80 | -300 |
| 4 | obs.go RecentEvents 替代 LastTransitions + InFlightSnapshot 进 PDR step obs(解 P0-2) | +60 | -20 |
| 5 | reaction marker → ReactionType enum 进 events(解 P0-3);ADR-0018 标 ACCEPTED + ADR-0017-v4 rename .v4-superseded | +20 ADR | -20 ADR |

净 ~+480 / -400,净 +80 LOC(但删 substate 抽象后整体清晰度 ↑)。

## Tradeoffs

### 收益
- 解 P0-1/P0-2/P0-3 三个 RL 可观测性漏洞 — RL 可从 obs.Events 唯一推理所有 game rule(含反应类型 /
  反应链层级 / PDR in-flight)
- 砍掉 substate 抽象 → 减 ~300 LOC + 概念简化(没"私有跨步 state"这种 misnomer)
- ctx 减重 → hook 作者代码更清晰(transient vs persistent 边界明确)
- 事件 typed first-class → 调试 / replay / analytics 全部受益

### 代价
- prototype 大改造(重构 ~480 LOC)
- DecisionSpec union 字段扩张(5 种 → 6 种,每种多 1-2 typed field)
- ContainerID 引入(Scalar/Collection 加 ID 字段,declare 时分配 + obs/event 引用 id 而不是 ptr)
- Event ring N=64 vs 当前 16 — 内存 4x(每 Event ~120 byte * 64 = 7.5KB per game),Clone 成本同比上升

### 不做的事

- Event ring N=64 是否够覆盖最长反应链 + sleep round(open question)
- ReactionType enum 13 类是否覆盖原神所有反应 — 开放,加新反应改 enum
- DecisionSpec union 字段越扩越多,是否考虑 sum type per Kind 拆 struct(Go 没真 sum,prototype 阶段
  union struct 已够)

## Open Questions

1. **ContainerID 形态**:`int` 还是 `string`?建议 int,ContainerID typed 类型,debug 时用 Scalar.Name 反查
2. **Event ring N**:16 → 64 够吗?还是 128?建议 64
3. **substate 砍掉后 v4 prototype 26 个 substate-related test 怎么处理**?建议方案 a(千织/烈絮 test
   改 DecisionSpec one-shot 保留覆盖)

## v5 路径后续被取代

[`../0019-dsl-v6-semantic-engine/`](../0019-dsl-v6-semantic-engine/) 选择 v1 增量改造路线,不上线 v4
prototype 也不上线 v5 event-sourcing。

跟 [`../0017-dsl-v4/`](../0017-dsl-v4/) 关系:v4 prototype 落地的 typed schema(Item / 10 enum /
DecisionSpec / Owner / HiddenFrom / form-bound hook / A16 tombstone / A2-rev group reject / A24 cost
auto-resolve)**本 ADR 全部保留**,只动 substate + ctx + transition log 三处。

## References

- `docs/2_decisions/adr-0018-dsl_v5_event_sourcing.md` (mirror)
- [`../0017-dsl-v4/`](../0017-dsl-v4/) — v4 prototype 30 axiom 基础
- [`../0019-dsl-v6-semantic-engine/`](../0019-dsl-v6-semantic-engine/) — 后续取代
- `gicg_engine/v2/substate.go` — 被砍掉的过度抽象
- `gicg_engine/v2/event.go` — 拟新建 typed Event log(实际未实施)
