---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: pipeline-async-weight-sync
---

# Design — 统一 pipeline driver async weight sync

## 1. 现状(confirmed bug,证据见 proposal §1)

```
run_pipeline loop (pipeline.py:106-193):
  collect  → collector.collect(plan.n_episodes, provider)   # drain ring only
  train    → loss/backward/optimizer.step (更新 parent network)
  [GAP]    → ❌ 无 collector.sync_weights — actor 进程权重永不更新
  eval     → eval_server.run_jobs
  ckpt     → ckpt_mgr.save + opp_pool.add_snapshot

async collector _bootstrap (one-shot, _spawned guard):
  publish version-0 weights ONCE → actor 整 run 用初始权重
```

parent 的 `network`(`optimizer.step` 更新它)与 actor 进程的权重副本
(InferenceServer / WeightsSHM 里 `_bootstrap` 时的 version-0 copy)**是两份**;
没有 re-publish,actor 副本永远 stale。

## 2. 设计目标

driver 在每次(或每 N 次)train 后,把 learner 的 `network` 权重 republish 给
actor —— 复活 legacy `async_loop.py:176-186` 的 `sync_weights_every_train_steps`
cadence,但收口在 paradigm-agnostic driver,4 个 async paradigm 共享。

约束:
- serial path 零行为变化(serial 共享 in-proc network,本不需 sync)。
- async collector 的 `sync_weights` 实现**已存在且正确**(只是没被调),不动。
- driver 保持 paradigm-agnostic(不 hardcode "async"/"MCTS"/具体 collector 类)。

## 3. Decision D1 — cadence 机制

### (A) StepPlan flag + paradigm step_schedule 翻 (推荐)

- `StepPlan` 加 `sync_weights: bool = False`(mirror `clear_buffer_after_train`)。
- driver:`if plan.sync_weights and hasattr(collector, 'sync_weights'):
  collector.sync_weights(network)`。
- 各 paradigm `step_schedule` 在 (async mode + steady-train iter) 时,按
  `state.train_steps % cadence == 0` 翻 bit;serial mode 恒 False。
- **优点**:与既有 `clear_buffer_after_train` epilogue 模式一致;cadence 是
  paradigm 决策(paradigm 最懂自己 stale 容忍);driver 不知道 "async" 概念
  (paradigm-agnostic 保持);hasattr guard 让 serial/无 sync collector no-op。
- **缺点**:4 paradigm step_schedule 各加一段(但都是同形 ~8 LOC)。

### (B) driver-level cadence via [pipeline] cfg

- driver 读 `cfg.pipeline.sync_weights_every` + `cfg.pipeline.mode=='async'`,
  自己按 `state.train_steps % every == 0` 触发,不经 StepPlan。
- **优点**:4 paradigm step_schedule 零改;统一 `[pipeline]` 字段。
- **缺点**:driver 要懂 "async" + cadence 语义(违背 paradigm-agnostic);
  weight-sync 语义从 paradigm 上移到 driver,与 `clear_buffer_after_train`
  (paradigm-declared)不一致。

### 推荐 A

paradigm-declared epilogue(A)与 driver 现有架构(StepPlan flags 驱动一切
paradigm 偏差,见 pipeline.py docstring "every deviation goes through StepPlan
flags")一致。driver 只新增"honor 一个 bool flag",不引入 mode/cadence 知识。

## 4. Decision D2 — cadence cfg 字段命名

现状:AZ legacy `AZConfig.sync_weights_every_train_steps=10`(config.py:171,但
**`AZParadigmConfig` 没有**);DMC `DMCParadigmConfig.weight_sync_every_steps=0`
(config.py:88,`0=每 iter sync`);CFR/PPO **无**。

### (统一,推荐) `sync_weights_every_train_steps: int`

- 各 async paradigm 的 ParadigmConfig 统一加 `sync_weights_every_train_steps`
  (复用 AZ legacy 名,语义清晰:每 N train steps sync 一次,`0/1`=每次)。
- DMC `weight_sync_every_steps` → rename 对齐(breaking cfg field,但 DMC
  async cfg 只 `stage3_b_v_legacy.toml` 一处,同步改)。
- **优点**:跨 paradigm 一致,reader/工具不需记 4 个名。
- **缺点**:DMC rename = 1 处 cfg + 字段改。

### (各自名) 保留 paradigm-local 命名

- 每 paradigm 用自己习惯名,step_schedule 读各自字段。
- **优点**:zero DMC churn。**缺点**:4 名不一致,长期维护负担。

### 推荐 统一

命名一致性收益 > 1 处 DMC rename 成本;async cfg 极少(单 cfg),rename 风险低。

## 5. Decision D3 — scope(几个 paradigm 一起做)

### (4 全做,推荐)

driver gate 一次修(通用);AZ/DMC/CFR/PPO step_schedule 各加 sync bit + cfg 字段。
- **优点**:无 half-fixed 遗留;DMC async(已 production 跑过 + collapse)立即受益;
  AZ async(az-mp-pool-unification T4-T8)前置就绪;CFR/PPO async 未来开箱可用。
- **缺点**:touch 4 paradigm(但每个同形小改)。

### (增量) 只修 driver + DMC/AZ

CFR/PPO step_schedule + cfg 留 follow-up。
- **优点**:scope 小。**缺点**:CFR/PPO async 留 latent 同 bug(silent)。

### 推荐 4 全做

driver gate 已通用,4 paradigm 加 cadence 边际成本低;避免 CFR/PPO 留同一 latent
bug(下次有人开 CFR/PPO async 又踩)。

## 6. 实现要点

1. `protocols.py`:`StepPlan.sync_weights: bool = False`。
2. `pipeline.py`:train block 后(L153 后、clear_buffer L159 前)加 honor 块。
3. 各 paradigm `step_schedule`:steady-train 分支(已 train=True 那支)按
   `cfg.pipeline.mode=='async' and state.train_steps % max(1,cadence)==0` 翻
   `sync_weights=True`。warm-up / done 分支不翻。
4. ParadigmConfig:AZ/CFR/PPO 加 `sync_weights_every_train_steps`,DMC rename。
5. AZParadigm:`AZParadigmConfig` 加 cadence 字段(legacy AZConfig 已有,但
   unified 路径走 AZParadigmConfig — 必须加,否则 AZ async 读不到 cadence)。

## 7. Risk

- **cadence=0 边界**:`train_steps % 0` ZeroDivisionError → 用 `max(1, cadence)`;
  `0`/`1` 都语义 "每 train iter sync"。
- **首次 sync 时机**:warm-up(collect-only)期不 train → 不 sync(actor 用初始
  权重 collect warm-up 数据,可接受:warm-up 本就是 bootstrap 阶段)。steady 期
  第一次 train 后即 sync。
- **serial 误触**:serial collector 无 `sync_weights` → hasattr guard no-op;
  且 step_schedule 在 serial mode 不翻 bit(双保险)。
- **DMC rename breaking**:`stage3_b_v_legacy.toml` 的 `weight_sync_every_steps`
  需同步改名,否则 strict cfg loader unknown-key fail(可被 grep 验)。
- **验证 collapse 关联**:fix 后 re-run run 149(DMC async)对比 collapse 是否消失
  —— 是 fix 后独立 follow-up,本 change 只负责 weight sync 正确性(单元 + e2e
  test 验 actor 收到 version bump)。

## 8. 测试策略

- driver unit:mock collector(records sync_weights calls)+ StepPlan.sync_weights
  True/False → 验 honor + hasattr guard(无 sync_weights 的 collector 不 crash)。
- per-paradigm step_schedule unit:async mode + train_steps 序列 → 验 sync bit
  在 cadence 边界翻;serial mode 恒 False。
- e2e(扩现有 `test_*_async_mp_e2e`):2-actor 真 spawn,train 若干 iter 后断言
  actor 端 weight version > 0(收到 republish),非恒 version-0。
