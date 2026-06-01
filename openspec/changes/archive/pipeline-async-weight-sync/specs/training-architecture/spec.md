---
change_id: pipeline-async-weight-sync
capability: training-architecture
delta_type: ADD
target_subtopic: pipeline
---

# Spec Delta — training-architecture / pipeline

## [ADD] async weight sync in run_pipeline

**Motivation**:统一 `run_pipeline` 主循环此前从不调 `collector.sync_weights`,导致
async collector 的 actor 进程整个 run 用 `_bootstrap` 时 publish 的 version-0 初始
权重做 selfplay/rollout,learner 孤立训练(confirmed cross-paradigm bug,2026-05-29;
疑似 DMC Stage 3 run 149 collapse root cause)。

### SHALL #N — driver weight republish

`run_pipeline` SHALL,在每个 iteration 的 train block 之后、`clear_buffer_after_train`
/ eval / ckpt 之前,当 `plan.sync_weights` 为 True 且 `collector` 暴露
`sync_weights` 时,调用 `collector.sync_weights(network)` 把 learner 当前权重
republish 给 actor。

- `collector.sync_weights` 缺失时(serial collector:`AZSelfPlayCollector` /
  `DMCSerialCollector` 无此 method)driver SHALL no-op(`hasattr` guard),不得
  raise —— serial 模式 actor 与 learner 共享 in-proc network,无需 republish。
- republish 位置 SHALL 在下一轮 `collect` 之前,使 actor 下一批 collect 用到的是
  本轮 train 后的权重。

### SHALL #N+1 — StepPlan.sync_weights field

`StepPlan` SHALL 含 `sync_weights: bool`(default False),由 `paradigm.step_schedule`
按各自 cadence(`ParadigmConfig.sync_weights_every_train_steps`)在 async 模式的
steady-train iteration 翻为 True;serial 模式与 warm-up/done iteration SHALL 保持
False。这与既有 `clear_buffer_after_train` 同属 paradigm-declared epilogue flag
模式 —— driver 不感知 "async"/cadence 语义,仅 honor flag。

### SHALL #N+2 — async collector sync_weights contract

每个 async collector(`{DMCMultiProcessCollector, CFRAsyncCollector,
AZAsyncCollector, PPOAsyncCollector}`)SHALL 实现 `sync_weights(network)`,把
`network` 的当前(CPU-detached)权重 republish 到其 actor 权重通道
(InferenceServer.push_weights / WeightsSHM.publish_weights),使 actor 下次读取
拿到 version 单调递增的新权重。

## Code references (implement 后,2026-06-01)

- `training/core/protocols.py:StepPlan.sync_weights` — flag 定义(default False)
- `training/core/protocols.py:async_sync_weights_due` — cadence+mode gating helper
  (4 paradigm step_schedule 共享,DRY)
- `training/core/pipeline.py:_maybe_sync_weights` + `run_pipeline` — train 后 honor 块
  (hasattr-guarded;module-level helper 让 test 真调 production code)
- `training/paradigms/{az,dmc,cfr,ppo}/paradigm.py:step_schedule` — steady 分支调
  `async_sync_weights_due` 翻 bit(warm-up/done 不翻)
- `training/paradigms/{az,dmc,cfr,ppo}/config.py:ParadigmConfig.sync_weights_every_train_steps`
  — default **0**(D-c 沿用 DMC;DMC 由 `weight_sync_every_steps` rename)

## Test references (2026-06-01)

- `training/tests/test_pipeline_sync_weights_gate.py` — `_maybe_sync_weights` driver
  honor + hasattr guard(serial stub collector 不 crash)
- `training/tests/test_step_schedule_sync_weights_bit.py` — helper unit + 4 paradigm
  step_schedule wiring parametrize(async 翻 / serial 恒 False)
- `training/tests/test_paradigm_sync_weights_cadence_cfg.py` — 4 paradigm cadence 字段
  default-0 + DMC rename strict-loader reject
- `training/tests/test_pipeline_async_weight_sync_e2e.py` — driver-integration e2e
  (fake paradigm 真跑 run_pipeline async → driver 调 sync_weights;serial 不调)
- 真-spawn republish:`training/tests/test_cfr_async_mp_e2e.py`(collector.sync_weights
  → WeightsSHM 2-slot version bump,本 session 实跑 PASS)
