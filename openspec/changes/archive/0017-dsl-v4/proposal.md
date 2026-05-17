# DSL v4 — RL-pipeline-rewrite enabled, 30 axiom (prototype 实证修订)

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0017-dsl_v4.md` at P1-T1)
**Original date:** 2026-04-30 (last-rev 2026-05-01)
**Original status:** PROPOSED (prototype Stage 1-10 全 PASS;Phase 0 未启动);后被 ADR-0019 路线
取代未上线
**Supersedes:** v1 / v2 / v3 历史(`adr-0017-dsl_v2*.md.v{1,2,3}-superseded` 已 git rm at P1-T1)
**Superseded by:** [`../0018-dsl-v5-event-sourcing/`](../0018-dsl-v5-event-sourcing/) 局部修补 +
[`../0019-dsl-v6-semantic-engine/`](../0019-dsl-v6-semantic-engine/) supersede-on-implementation

## Why

- **v1 (current)**: 24 typed hookType + 自动扣 dice + engine 硬编 game rules,18 张代表卡 1 张干净覆盖
- **v2 (1.0, 补丁化)**: 4-phase + Channel + helper,reviewer 22 项问题,user 否决
- **v2 (2.0, 15 axiom)**: 11/20 卡 ⛔
- **v3 (23 axiom)**: 8/20 干净(改善),3 张 ⛔ + 致命 closure 信息泄漏(A19) + 跟 RL pipeline 不
  对齐(cgo/obs/ckpt 全废没 plan)
- **v4 (28 axiom)**: 6 axiom 修订 + 6 axiom 新增 + RL pipeline migration spec
- **v4 prototype** (本 ADR rev): 745 LOC prototype 实证 + A2 修订加 source_hook_id + A30 新增
  PDR-sync-with-hold,合计 30 axiom (A1-A30) + A31 L3 obs typed transition log

user 已确认 3 个核心决策点(2026-04-30):
- A24 cost payment auto-resolve(90% 卡 engine 自动选最小 dice 子集,RL 视角跳过 cost step)
- 全 ckpt 失效可接受,重训 Stage 0-3 baselines + r009 BC + r010 AZ-warmstart
- 允许破坏现有 RL pipeline(cgo schema / obs encoder / BC dataset / 重写)

## What

**Axiom 集合 31 条**(A1-A31,基础架构 / engine 框架 / RL 可感知 / 修饰能力 / 新增 first-class
概念):
- A1-A9 基础架构:容器三类 / propose-resolve-commit-rollback / 无 Channel / hook 顺序 declared
  dependency / 三层 pipeline / Effect atomic + multi-step substate / Reaction = SubAction propose
  hook / Layer 2 helper 不在 engine / 严格 single stack
- A10 Engine 框架最小化,16 项基础设施
- A11-A14 RL 可感知:Forward-simulatable atomic step / Action 枚举 pure function + perf 目标 / Reward
  commit 后 player-level 累加 / Hidden info ownership-bound
- A15 修饰能力 first-class
- A16-A31 新增 first-class 概念:hook lifecycle owner-bind + tombstone GC / Form 替换 / Player
  decision via substate / closure plain-data view / substate state first-class / provenance chain
  (max 32) / TriggerSource enum + IsPlayerAction() / stdlib whitelist / Cost payment auto-resolve /
  PDR async + sync-with-hold / Multi-instance substate / instance lifecycle / Hierarchical obs /
  Attached entity / **A30 PDR-sync-with-hold** / **A31 L3 obs typed transition log**

**Prototype 实证**(`gicg_engine/v2/`, ~2640 LOC, 25 tests PASS):
- ✓ A11 forward-simulatable atomic step (Game.Clone bit-exact, 含 typed Items + LastTransitions)
- ✓ A2 propose-resolve-commit + A2-rev source_hook_id 整组 reject
- ✓ A30 PDR-sync-with-hold 解 #10 勘探钻机 fundamental flaw
- ✓ A22 ctx 字段 filter 取代旧 silent_kind 白名单
- ✓ A16 owner-detach hook lifecycle (tombstone GC)
- ✓ A24 cost auto-resolve O(N)
- ✓ A26 multi-instance substate + recycle pool
- ✓ A19 plain_key_fn typed dispatch
- ✓ A14 ownership-bound mask + SwapCollections
- ✓ A17/A29 form-bound hook auto-skip + skill_set replace
- ✓ A13 reward attribution at commit (rollback 不累加)
- ✓ A12 perf microbench: 1k Clone + 1k FireSubAction
- ✓ E2E 反应链综合 (火+水→蒸发+万叶 boost = 5 dmg)
- ✓ A31 L3 obs typed transition log (TestL3ObsLastTransitions, ring buffer bounded 16)

**全 typed schema 落地**(no `any`, no `map[string]any`, no mock, no placeholder):Item interface + 3
concrete + 10 typed enum + DecisionSpec/Result typed sum + SubstateInitData/ExitData typed union +
MarkerRef declared marker。

**Migration Plan + LOC 估算**:
| Phase | 新增 | 修改 | 删除 |
|---|---|---|---|
| Phase 0 engine 框架重写 | ~3800 | ~1400 | ~2150 |
| Phase 1 system DSL 重写 | ~3600 | — | ~800 |
| Phase 1.5 RL pipeline migration | ~1900 | ~1050 | (全 ckpt) |
| Phase 2 验证 + retrain | ~1700 | ~600 | — |
| Phase 3 cleanup | — | ~750 | ~150 |
| **合计** | **~11000** | **~3800** | **~3100** + 全 ckpt |

## Affected specs

- `engine-dsl` (重写,v4 axiom 集是 source spec 依据;P1-T2/T6 抽 SHALL 时 backfill)
- `engine-pipeline` (新建,三层 Action/SubAction/Mutation)
- `engine-hooks` (重写,propose/resolve/commit/rollback + lifecycle)
- `engine-obs` (A28 hierarchical encoding + A31 L3 transition log)
- `engine-pdr` (新建,A25 async + A30 sync-with-hold)
