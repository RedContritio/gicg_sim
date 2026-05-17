# DSL v5 — Event-sourcing 替代 substate + ctx 减重

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0018-dsl_v5_event_sourcing.md` at P1-T1)
**Original date:** 2026-05-01
**Original status:** PROPOSED (尚未 prototype, 跟 v4 prototype 部分推翻);后被 ADR-0019 路线取代
未上线
**Supersedes:** [`../0017-dsl-v4/`](../0017-dsl-v4/) 部分(A20 substate first-class / A26 multi-instance
substate / A28 hierarchical obs / 部分 A18 PDR via substate);keeps A1-A17 / A19 / A21-A25 / A27 /
A29-A31
**Superseded by:** [`../0019-dsl-v6-semantic-engine/`](../0019-dsl-v6-semantic-engine/)
supersede-on-implementation

## Why

基于 v4 prototype (`gicg_engine/v2/`) opus subagent 评审 + user 设计反馈触发的根本性重构。改动范围
涉及 v4 prototype 大头。

### 问题 1: substate 抽象过度设计

v4 prototype `gicg_engine/v2/substate.go` 引入 `SubstateInstance.Scalars/Collections + LegalActions/
OnAction + Recycle pool`,假设 RL 在 substate 内可能多步交互。但 GICG 实际场景全部是 **one-shot
decision**:

| 场景 | "看似多步" → 实际 |
|---|---|
| 千织 3-of-4 召唤物挑选 | RL 一次返回 `SelectedIndices=[0,2,3]`,不分 3 step |
| 勘探钻机 BinaryChoice | RL 一次返回 `ChosenBinary=1`,不分 2 step |
| 烈絮 sub-skill 选 | RL 一次返回 `ChosenSkillIdx=2`,不分 N step |
| Cost payment | RL 一次返回 `PaidDice=[Fire,Fire,Anemo]`,不分 N step |
| 投骰子 → 看 → 重投 | 这其实是两个独立 game step (engine random 在中间),不是 substate 内多步 |

→ `SubstateInstance.Scalars / LegalActions / OnAction / Recycle pool` **无真实需求**,过度设计。

### 问题 2: ctx 太重 + transient 不进 obs

v4 `Ctx` 持 `Proposals / NestedSubActions / HoldFor / DecisionResult / Provenance` 等 transient state。
但 transient = commit 后就消失,**不进 obs**。opus subagent 评审找出 3 个 P0 漏洞:

- **P0-2**: PDR sync hold 时 RL 看不到 in-flight ctx(勘探钻机受伤 dmg 量丢失)
- **P0-3**: PropMarker commit noop 不进 LastTransitions(蒸发/融化/扩散 反应类型 RL 黑盒)
- (P0-1 由问题 1 自动消解)

→ ctx + LastTransitions ring 是混合设计,信息有损丢失。

## What

1. **替换 LastTransitions ring → typed Event log(event-sourcing)** — 全部 SubAction / Action /
   proposal / reject / commit / rollback / decision / destroy / reaction 都是 typed Event。
   `EventKind` 11 类;`Event` struct 含 SubAction/Action 共通字段 + Proposal snapshot + Reaction
   (typed ReactionType enum 13 类) + PDR + Commit;**`SubActionSnapshot`** 解 P0-2(PDR step 时 RL
   看到 in-flight 当前 ctx 状态,含 AccumulatedDelta map[ContainerID]int + Markers)
2. **`Game.Events` ring**(替代 `LastTransitions`)bounded N=64;`NextEventID` 全局自增;`EmitEvent`
   helper
3. **ctx 减重(只保留 hook 间临时通信)** — 移除字段:`Provenance`(改通过 events 串 ParentID)、
   `PendingDecisions`(改通过 events `EvDecisionRequested`)、`Cancelled`(改通过 `EvSubActionRollback`)
4. **substate 整体折叠 → DecisionSpec 扩张** — 砍掉 `gicg_engine/v2/substate.go` 整文件(~213 LOC);
   删 `SubstateInstance / SubstateTemplate / SubstateRegistry / SubstateField / SubstateAction /
   SubstateActionKind / SubstateInitData / SubstateExitData / DecisionEnterSubstate`;DecisionSpec
   扩 6 kind(SelectFromCollection / BinaryChoice / TargetChar / CostPayment / SelectSkill / RerollDice)
5. **obs.RecentEvents 替代 LastTransitions** — `ObsSnapshot.RecentEvents []Event` + `PendingDecision
   *DecisionSpec` + `InFlightSnapshot *SubActionSnapshot`(解 P0-2)
6. **A20 OBSOLETE + A26 OBSOLETE + 新增 A32 Event-sourcing first-class** — axiom 数 31 → 30(删 A20
   + A26,加 A32)

## Affected specs

- `engine-event` (新建 typed Event log + EventKind + ReactionType)
- `engine-obs` (改 RecentEvents + PendingDecision + InFlightSnapshot)
- `engine-pdr` (DecisionSpec 6 kind union;一次性多 idx)
- `engine-dsl` (axiom A20 / A26 OBSOLETE,A32 NEW)
