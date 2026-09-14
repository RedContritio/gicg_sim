---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
capability: training-architecture
---

# Training Architecture — paradigm-agnostic 训练流水线骨架

> 本 capability spec 治理 GICG RL training 的**架构层**约定:`training/`
> 目录布局、paradigm 接口契约、pipeline driver、network 共享、eval 协
> 议、opponent mix。各 paradigm(AZ / DMC / CFR / PPO / BC)的具体超参
> 与算法实现由各自 paradigm dossier 治理,不属本 spec 范围。
>
> 2026-05 的 unified-training-pipeline 已落地；当前接口和行为以
> `training/core/`、`training/paradigms/` 及各 subtopic 为准。

## 1. Purpose

迁移前的 `training/` 三层布局(`framework/` + 各算法目录)
是 2026-04 PPO + AZ + CFR 并存时期演化产物。新加入 DMC + BC + 后续
paradigm 后,需要把 paradigm-agnostic infra 与 paradigm-specific 算法显
式分离,避免:

- `framework/` 与各 paradigm 之间持续渗透(observed in DMC Phase 3.5)
- Actor / eval 各自实现 episode loop,导致 paradigm × runner 笛卡尔积
- Inference placement(local / remote)与 device(cpu / mps / cuda)硬编
  码在各 paradigm,无法横向迁移
- BC 作为辅助流程(embedded in AZ + PPO)无法独立配置或 scale

本 spec 提供 5 大类约束,锚定 P2 unified-training-pipeline change 的实
施边界:

- **Protocol contracts**(详 [`./protocols.md`](./protocols.md))
- **Pipeline driver**(详 [`./pipeline.md`](./pipeline.md))
- **Network sharing**(详 [`./network-sharing.md`](./network-sharing.md))
- **Eval protocol**(详 [`./eval.md`](./eval.md))
- **Opponent mix**(详 [`./opponent-mix.md`](./opponent-mix.md))

## 2. Scope

**In scope**:
- `training/core/` 与 `training/paradigms/<name>/` 二分目录布局(P2 物理
  迁移落地;骨架阶段先以 SHALL 形式锚定)
- 六个 paradigm-agnostic protocol(Paradigm / Collector / Buffer /
  LossComputer / EpisodePolicy / NetworkProvider)的接口契约
- Pipeline driver loop 与 serial / async 模式切换边界
- Encoder / heads 共享规则(paradigm-agnostic encoder + paradigm-specific
  heads)
- 周期 eval 流程与普通 actor 基建(EpisodeRunner / EpisodePolicy /
  EnvFactory / OpponentRegistry)复用契约；AZ 双边 self-play 使用专用适配器
- OpponentRegistry + baseline 接口的 paradigm-agnostic 注册表
- Cfg 多层继承字段(`device` / `seed`)与本 spec 的交互边界

**Out of scope**:
- 各 paradigm 内部算法实现细节(AZ MCTS 参数 / CFR regret update / PPO
  GAE 等)— 各自 paradigm dossier
- Obs / action 张量编码契约 — 待落地 `rl-obs` capability spec
- Cfg schema 字段完整列表 + 继承 resolver 实现 — 待落地 `config-schema`
  capability spec
- Eval scenario 设计(F1-Dn / mcts_pure / historical 池构造)—
  [`./opponent-mix.md`](./opponent-mix.md) 仅治理注册表接口,内容由 runs
  registry / scenario spec 承接
- Run lifecycle / artifact 命名 — [`tools-layout`](../tools-layout/spec.md)

## 3. Core SHALL invariants

本 capability 治理 25 条 SHALL invariant,覆盖 top-level layout / paradigm
protocol / network sharing / pipeline mode / eval isolation / weights sync /
BC first-class / encoder paradigm-agnostic / single entry tool / NetworkProvider
抽象 / EpisodeRunner contract / paradigm spec 引用 / config-schema 引用 /
tools-layout 引用 / e2e smoke 契约 / backbone unification / `make_env_factory`
公共契约(PA-EF1..6)。完整列表 + 详细约束见
[`./invariants.md`](./invariants.md)。

## 4. Paradigm landscape

本 capability 覆盖 5 个 paradigm,各自状态(unified-training-pipeline
P3-P5 ship 后)+ 对应 capability spec:

- **AZ**(AlphaZero):`training/paradigms/az/`。
  Tier `maintenance`。Spec → [`../paradigm-az/spec.md`](../paradigm-az/spec.md)。
- **DMC**(Deep Monte Carlo):`training/paradigms/dmc/`(first migration
  through unified pipeline P3-T8)。Tier `active`。Spec →
  [`../paradigm-dmc/spec.md`](../paradigm-dmc/spec.md)。
- **CFR**(Deep CFR):`training/paradigms/cfr/`。Tier `frozen-research`
  (r008 postmortem)。Spec → [`../paradigm-cfr/spec.md`](../paradigm-cfr/spec.md)。
- **PPO**:`training/paradigms/ppo/`。Tier `frozen`(Stage 3 closure)。
  Spec → [`../paradigm-ppo/spec.md`](../paradigm-ppo/spec.md)。
- **BC**(Behavior Cloning):`training/paradigms/bc/`(first-class,
  P4-T2 deduped from AZ/PPO embedded copies)。Tier `first-class`
  (production fallback)。Spec → [`../paradigm-bc/spec.md`](../paradigm-bc/spec.md)。

## 5. Subtopics

本 capability 由本文件 + 9 个 subtopic 组成。每个 subtopic 专注一组正
交规则,主 spec.md 只列 SHALL invariant 概要,细节落 subtopic。骨架阶
段(P0-T9)各 subtopic 仅锚定方向,详细实施留 P2 增量。

- [Core SHALL invariants](./invariants.md) — 25 条本 capability 硬约束 + 详细实施引用
- [Protocols](./protocols.md) — Paradigm / Collector / Buffer /
  LossComputer / EpisodePolicy / NetworkProvider 接口契约
- [Pipeline driver](./pipeline.md) — Driver 主循环 + collector-owned
  serial/async topology + PipelineState + StepPlan
- [Network sharing](./network-sharing.md) — encoder / heads 共享规则 +
  paradigm-specific head 边界 + ActorCritic 组装
- [Eval protocol](./eval.md) — Periodic eval + EpisodeRunner 复用边界
- [Opponent mix](./opponent-mix.md) — OpponentRegistry + mix sampling
  + baseline 接口 + historical ckpt
- [Paradigm onboarding](./paradigm-onboarding.md) — 如何接入第 6
  paradigm:contract surface + 5 paradigm 历史教训 + anti-pattern
- [Smoke 契约](./smoke-contract.md) — paradigm-agnostic smoke test
  contract(default tier 5 SHALL + 5 paradigm-specific probe)+
  smoke_full tier 协议(A1.6.1-A1.6.7,opt-in 全 driver e2e + ckpt
  save / resume verify)
- [Env factory 公共契约](./env-factory.md) — `make_env_factory` canonical
  signature + 6 SHALL invariants (PA-EF1..6) + paradigm 调用模式 +
  `env_factory_legacy.py` 退役历史
- [Actor backend](./actor-backend.md) — `cfg.pipeline.actor_backend` 分派
  + Go backend N+2 OS process topology + 0 cgo invariant + TCP-only inference
  + atomic spawn/shutdown (AB1-AB12,I29 R7 ship 2026-05-25)

## 6. Cross-references

**Sibling capability specs**:
- [`../config-schema/spec.md`](../config-schema/spec.md) — `device` +
  `seed` 继承字段 registry + R1-R7 placement schema + loader strictness
- [`../tools-layout/spec.md`](../tools-layout/spec.md) — `tools.runs.train`
  单入口 + 功能分类子目录 + 老 tools 合并 / archive 规则
- [`../paradigm-az/spec.md`](../paradigm-az/spec.md) — AZ 算法层 SHALL
- [`../paradigm-dmc/spec.md`](../paradigm-dmc/spec.md) — DMC 算法层 SHALL
- [`../paradigm-cfr/spec.md`](../paradigm-cfr/spec.md) — CFR 算法层 SHALL
- [`../paradigm-ppo/spec.md`](../paradigm-ppo/spec.md) — PPO 算法层 SHALL
- [`../paradigm-bc/spec.md`](../paradigm-bc/spec.md) — BC 算法层 SHALL
- `openspec/specs/rl-obs/`(待落地)— 训练侧 obs / action 张量编码契约
- Run lifecycle and metadata are specified by [`../tools-layout/spec.md`](../tools-layout/spec.md)
  数据契约(post `core-network-generic-promotion` 2026-05-17;pre-redesign archive
  在 `docs/5_history/runs_pre_redesign_2026_05_17.md`)

**Current code structure**(unified-training-pipeline P3-P5 ship 后):
- `training/core/` — paradigm-agnostic infra(protocols / pipeline /
  network / buffer / actor / inference / eval / opponent / config)
- `training/paradigms/<name>/` — 5 paradigm(`az` / `dmc` / `cfr` /
  `ppo` / `bc`),各含 paradigm implementation + adapters
- `training/framework/` 已删除(P5-F),全部融入 `training/core/`

**Decision artifacts**:
- ADR-0006 training layout(三层 framework / az / cfr 划分)→ P1 迁
  `openspec/changes/archive/0006-training-layout/`(原文
  `docs/2_decisions/adr-0006-training_layout.md`)
- DMC Phase 3.5 review(41 项 issues,部分由本架构吸收)→
  `docs/5_history/reviews/dmc_review.md`
- Eval service 当前协议 → [`../eval-protocol/spec.md`](../eval-protocol/spec.md)

## 7. Status

- **Created**:2026-05-15(P0-T9,骨架阶段)
- **Revised**:2026-05-16(unified-training-pipeline P6 archive merge —
  SHALL 2 详化方法签名 + SHALL 13-17 ADD NetworkProvider / EpisodeRunner /
  paradigm specs / config-schema / tools-layout 引用)
- **Revised**:2026-05-17(invariants split):第 3 节 105 行 17 SHALL
  invariants 拆到 `invariants.md` subtopic,主 spec.md 减肥到 ~165 行以
  为后续 archive merge(parent + env-factory + smoke_full)预留空间
- **Revised**:2026-05-17(`core-network-generic-promotion` archive):
  invariants 从 17 条扩展到 **19 条** — ADD #18 smoke 契约 + #19 backbone
  unification;paradigm-onboarding.md +Smoke 契约 / paradigm-specific probe
  章节;network-sharing.md +Backbone unification 章节 + DI 接口 MODIFY +
  PPO outlier 描述 REMOVE
- **Revised**:2026-05-17(parent change fixup):paradigm-onboarding.md §8
  Smoke 契约段拆到独立 `smoke-contract.md` subtopic(paradigm-onboarding.md
  458 行超 file-layout §1.1 subtopic ≤ 400 cap);Subtopics 索引 + Status
  section SHALL count 17 → 19 同步
- **Revised**:2026-05-17(`env-factory-unification` archive):invariants
  从 19 条扩展到 **25 条** — ADD #20-#25 (PA-EF1..6) `make_env_factory`
  公共契约;新 subtopic `env-factory.md` 承接 canonical signature + usage
  examples + retirement of `env_factory_legacy.py`;Subtopics 索引 8 → 9
  + SHALL count 同步
- **Revised**:2026-05-17(`paradigm-smoke-full-tier` archive):
  invariants.md SHALL #18 扩展为 two-tier(default smoke + opt-in
  smoke_full,7 子约束 A1.6.1-A1.6.7 落 smoke-contract.md §4);
  smoke-contract.md +§4 smoke_full tier 协议 + §5 tier 区分 quick
  reference + §6.1 DECISIONS 索引(SF-101..106 + D-304/305 closure);
  关闭 parent change `core-network-generic-promotion` D-304 / D-305
  deferred items;invariants 条数不变(SHALL #18 字段扩 sub-clauses 不算
  新条)
- **Revised**:2026-05-17(`ppo-structural-backbone-migration` archive):
  invariants.md SHALL #19 closure update — PPO outlier 退役完成,5 paradigm
  100% 闭环(原 "follow-up change propose" → "archive ship")
- **Revised**:2026-05-17(`bc-pipeline-collect-gate-fix` archive):
  pipeline.md §3 SHALL +1 → #7 `Collect phase gate SHALL be plan.collect
  only` — 闭 4 个 SF-105 follow-up 中最后一个 BC pipeline-path portion
  (fixture portion 由 `bc-smoke-dataset-fixture` 闭);5 paradigm
  smoke_full 全 PASS。pipeline.md 章节 SHALL count 6 → 7,invariants.md
  count 不变(SHALL #7 住 pipeline.md subtopic 而非主 invariants 列表)
- **Version**:0(unified-training-pipeline 在骨架上落地,无 schema 破
  坏 → 仍 v0)
- **Expected revision triggers**:
  - 新 paradigm 加入(超出当前 5 个)→ Paradigm protocol 可能扩展
  - DMC Phase 3.5 review 41 项 issues 决议变更架构边界
  - Async pipeline 实测后调整 weights snapshot slot 数 / SHM ring 设计
  - G2 cgo step + encode 合并 follow-up change(条件触发)→ Encoder
    SHALL 11 可能扩展
