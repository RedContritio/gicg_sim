---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: pipeline-async-weight-sync
---

# Proposal — 统一 pipeline driver 接入 async weight sync

## 1. Why

**Confirmed cross-paradigm driver bug**(2026-05-29,AZ mp-pool 统一 T4 审计撞到,
两 subagent + grep 三方一致):

`training/core/pipeline.py:run_pipeline`(统一 driver,所有 paradigm 的 production
入口)主循环 `collect → train → eval → ckpt` **从不调 `collector.sync_weights`**。

- 全仓 `grep sync_weights`:DMC/CFR/PPO/AZ 四个 async collector **都实现了**
  `sync_weights`(`{dmc/collector,cfr/_async,ppo/_async,az/_async}.py`),但**唯一
  调用者是 test 文件**(`test_*_async_mp_e2e.py`)。零 production driver 调用。
- async collector 的 `_bootstrap` 在启动时 publish **一次 version-0 权重**(AZ
  `_async.py:120` `server.push_weights` / DMC `collector.py:212`
  `runtime.publish_weights`),之后 `collect` 只 drain ring,**永不 re-publish**。
- 后果:**actor 进程(独立 spawn,经 InferenceServer / WeightsSHM 拿权重)整个
  run 用初始随机权重做 selfplay/rollout,learner 在孤立训练**。actor 端接收机制
  (WeightsWatcher 轮询 / InfServer re-query)已建好,只缺 driver 端触发。
- 违背 legacy 契约(`docs/1_specs/network/current.md:419` "每
  `sync_weights_every_train_steps=10` 次 train 后 push weights"):统一 pipeline 下
  stale gap **无界**(整个 run),而非 legacy 的 10-30 games。

**很可能是 Stage 3 collapse(run 149) 的 root cause / major contributor**:DMC 是
唯一真跑过 async production 的 paradigm(`configs/dmc/stage3_b_v_legacy.toml`
`mode="async"` `num_actors=16`)→ artifact `202605271150_000149` = memory
`project_stage3_pilot_policy_collapse_2026_05_28` 的 run 149(0/256 vs F1-D2)。
weight sync gap 是比 PLAN.md §A.2 的 `ε + MC return self-reinforcing argmax`
(下游 mechanism)更**上游**的 data-staleness:actor 用 never-updated 初始策略生成
**全部** selfplay 数据,learner 拟合"随机初始策略 self-play",单独足以致 collapse。
**需 fix 后 re-run run 149 验证才能定 root cause**。

这是 AZ async(`az-mp-pool-unification` T4-T8)的**硬前置**:不修则 AZ 切 async 同样
collapse。修复属于 driver(`run_pipeline` + `StepPlan`),非任一单 paradigm —— 故
单开本 cross-paradigm change(而非塞进 az-mp-pool-unification)。

## 2. What

**driver-level weight-sync cadence**(LOC ~ +60):

1. **`training/core/protocols.py:StepPlan` 加 `sync_weights: bool = False`**
   (mirror `clear_buffer_after_train` 的 paradigm-declared epilogue 模式)。
   off-policy/serial 默认 False(行为不变)。

2. **`training/core/pipeline.py:run_pipeline` 在 train block 后 honor**:
   ```python
   if plan.sync_weights and hasattr(collector, 'sync_weights'):
       collector.sync_weights(network)
   ```
   位置:train block 之后、`clear_buffer_after_train` / eval / ckpt 之前(actor
   下一轮 collect 前拿到新权重)。`hasattr` guard:serial collector
   (`AZSelfPlayCollector` / `DMCSerialCollector`)无 `sync_weights`(serial 共享
   in-proc network 不需 sync),guard 防 AttributeError。

3. **各 paradigm `step_schedule` 在 (async mode + steady train) 时按 cadence
   翻 `sync_weights` bit**:`train_steps % cadence == 0`。cadence 来自各
   ParadigmConfig cfg 字段(D2 定命名)。serial mode 恒 False。

4. **cadence cfg 字段统一**(D2):各 async-capable paradigm 的 ParadigmConfig 加
   `sync_weights_every_train_steps: int`(复用 AZ legacy 名;DMC 现有
   `weight_sync_every_steps` rename 对齐)。

## 3. Affected specs

- `openspec/specs/training-architecture/` — pipeline-driver subtopic:
  - **[ADD]** SHALL:run_pipeline 在 train 后 SHALL 按 `StepPlan.sync_weights`
    调 `collector.sync_weights(network)`(hasattr-guarded);async collector
    SHALL 实现 `sync_weights` 把 learner 权重 republish 给 actor。
  - StepPlan schema 加 `sync_weights` field 文档。

## 4. Out of scope

- **不改** async collector 各自的 `sync_weights` 实现(已存在且正确,只是没被调)。
- **不改** actor 端接收机制(WeightsWatcher / InfServer re-query 已 ship)。
- **不动** serial path 行为(serial 共享 in-proc network,本就不需 sync;hasattr
  guard 使其 no-op)。
- **不解** Stage 3 collapse 本身(本 change 修 root-cause-suspect 的 weight sync;
  collapse re-run 验证是 fix 后的独立 follow-up)。
- **不引入** 新 actor backend / wire 类型。
- **不动** az-mp-pool-unification 的 AZ-local 改造(本 change 是其前置,正交)。

## 5. Decision summary (详 design.md D1-D3)

- **D1 cadence 机制**:推荐 **A (StepPlan flag + paradigm step_schedule 翻)** —
  与 `clear_buffer_after_train` 同 pattern,paradigm 自定 cadence,driver 保持
  paradigm-agnostic。 备选 B (driver 读统一 `[pipeline]` cfg 字段直接 cadence)
  更少 paradigm churn 但把 weight-sync 语义从 paradigm 上移到 driver。
- **D2 cadence cfg 命名**:推荐 **统一 `sync_weights_every_train_steps`** 全
  async paradigm(DMC `weight_sync_every_steps` rename)。 备选保各自名(less churn,
  more 不一致)。
- **D3 scope**:推荐 **4 async paradigm 全做**(AZ/DMC/CFR/PPO step_schedule 一起
  加 sync bit,driver 一次修)。 备选只修 driver + DMC/AZ(CFR/PPO follow),但
  driver gate 已通用,4 paradigm 一起加 cadence 边际成本低 + 避免遗留 half-fixed。

**Effort**:~ +60 LOC(StepPlan +1 field / pipeline.py +3 / 4 paradigm
step_schedule +~8 each / 4 cfg +1 field each)+ tests(driver sync gate +
per-paradigm cadence)+ 4 OpenSpec artifact。
