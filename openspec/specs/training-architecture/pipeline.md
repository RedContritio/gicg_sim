---
last_updated: 2026-06-01
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: pipeline
---

# Pipeline Driver — driver loop + serial/async 模式

> 本 subtopic 锚定 paradigm-agnostic driver 主循环的形态、serial vs
> async 模式切换边界、PipelineState 与 Schedule 结构。详细 driver
> pseudocode、SHM ring buffer 协议、weights versioning state machine
> 在 P2 `unified-training-pipeline` change 落地。

## 1. Scope

本 subtopic 覆盖:

- Driver loop 高层骨架(collect → push → sample → train → eval → ckpt)
- Serial 模式(单进程 / 同步)与 async 模式(N actor + K inf-server + 1
  learner + M eval-worker + 1 eval-server)的形态边界
- PipelineState dataclass(driver-持有 state,ckpt 序列化对象)
- ScheduleInfo(paradigm-specific 调度参数,step 函数返回)

不覆盖:

- 具体 SHM ring buffer 字段布局 / 锁协议(P2 落地)
- 具体 weights snapshot slot 数量(P2 后实测调整)
- 各 paradigm 内部 actor / collector 实现细节(各 paradigm dossier)

## 2. Driver loop 高层骨架

Driver loop 是 paradigm-agnostic 的最外层循环,所有 paradigm 共享一份
实现位于 `training/core/driver.py`。骨架(P2 落地完整 pseudocode):

```
while not terminated:
    samples = collector.collect(n_per_iter)
    buffer.push(samples)
    if buffer.ready():
        batch = buffer.sample(batch_size)
        losses = loss_computer.compute(network, batch)
        optimizer.step(sum(losses.values()))
    schedule = paradigm.step_schedule(state)
    if eval_trigger(state):
        eval_runner.trigger_async(snapshot_weights())
    if ckpt_trigger(state):
        save_ckpt(state, buffer, network, optimizer)
```

## 3. Core SHALL invariants

**核心 SHALL**:

1. Driver loop SHALL be paradigm-agnostic — 实现位于
   `training/core/driver.py`,不允许 import `training/paradigms/*`(SHALL
   3 in 主 spec)。

2. Driver loop SHALL operate through Paradigm protocol(详
   [`./protocols.md`](./protocols.md))— Collector / Buffer /
   LossComputer / Optimizer 由 paradigm 提供,driver 不实例化具体类。

3. Pipeline mode SHALL be selectable via cfg
   `pipeline.mode = "serial" | "async"`。Driver loop 本身 mode-agnostic,
   Collector 实现处理并行(详 §4 + §5)。

4. PipelineState SHALL be ckpt-able — 任意时点序列化,resume 后行为与
   中断前一致(包含 step / iter / schedule / RNG state 等;详 §6)。

5. Eval trigger SHALL be schedule-based(cfg `pipeline.eval_every_steps`
   等)且 SHALL trigger 异步 eval — driver loop SHALL NOT 阻塞等待
   eval 完成(详 [`./eval.md`](./eval.md))。

6. Ckpt cadence SHALL be cfg-driven(`pipeline.ckpt_every_steps`)且独
   立于 eval cadence — eval 不修改 PipelineState,ckpt 永远从最新
   state 落盘。

7. **Collect phase gate SHALL be `plan.collect` only** —
   driver SHALL gate the collect phase(`collector.collect(...)` +
   `buffer.push(...)` + `state.after_collect(...)`)by `StepPlan.collect`
   alone。Driver SHALL NOT additionally AND in `plan.n_episodes > 0`
   (或 similar "non-zero unit count" check)。`n_episodes` 是
   **collector-internal contract**(paradigm-aware metadata):
   episode-driven paradigm(AZ / DMC / PPO / CFR)emit actual episode
   count;dataset-driven paradigm(BC)emit `0` truthfully(no episode
   concept,DatasetCollector.collect ignores `n_units` per docstring
   contract,一次性 push 全 static dataset on first call)。Per
   `bc-pipeline-collect-gate-fix`(archived 2026-05-17)— pre-fix BC
   collector 永不被 driver 调用,buffer 永远空,train batches 全 skip,
   ckpts 写 random-init 权重虽然 file-existence contract 满足。

8. **Async weight republish SHALL be driver-honored** — `run_pipeline`
   SHALL,在每个 iteration 的 train block 之后、`clear_buffer_after_train`
   / eval / ckpt 之前,当 `plan.sync_weights` 为 True 且 `collector` 暴露
   `sync_weights` 时,调 `collector.sync_weights(network)` 把 learner 当前
   权重 republish 给 actor。republish 位置 SHALL 在下一轮 `collect` 之前,
   使 actor 下批 collect 用本轮 train 后权重。`collector.sync_weights`
   缺失时(serial collector 无此 method)driver SHALL no-op(`hasattr`
   guard),不得 raise —— serial 模式 actor 与 learner 共享 in-proc
   network,无需 republish。(per `pipeline-async-weight-sync`,archived
   2026-06-01 — pre-fix `run_pipeline` 从不 republish,async actor 整个
   run 用 version-0 初始权重 selfplay,learner 孤立训练。)

9. **`StepPlan.sync_weights: bool` (default False)** SHALL 由
   `paradigm.step_schedule` 按各自 cadence
   (`ParadigmConfig.sync_weights_every_train_steps`)在 async 模式的
   steady-train iteration 翻为 True;serial 模式与 warm-up / done
   iteration SHALL 保持 False。这与既有 `clear_buffer_after_train` 同属
   paradigm-declared epilogue flag 模式 —— driver 不感知 "async" / cadence
   语义,仅 honor flag。

## 4. Serial mode

**形态**:单进程同步,actor + learner 在同一 Python 进程,collector
内部直接调 EpisodeRunner 顺序跑 N episode,然后 push → sample → train。

**适用**:smoke test / 小规模 debug / 单机低算力。

**SHALL**:

1. Serial mode Collector SHALL use LocalNetworkProvider with the
   same nn.Module instance as learner — 权重永远 in-sync,无 weights
   versioning。

2. Serial mode SHALL NOT spawn subprocesses — pickle / SHM 协议路径不
   触发,便于 debug。

3. Serial mode 与 async mode 的 driver loop SHALL be the same 实现 —
   差异完全在 Collector + NetworkProvider 内部。

## 5. Async mode

**形态**(P2 落地完整架构):

```
N ActorProcess  (env rollout, LocalNet × cfg.actor.device)
        ↓ samples via SHM ring
K InferenceServer  (Remote batched forward, cfg.infer.device)
        ↑ infer requests via IPC
1 Learner  (train loop, owns master weights, cfg.train.device)
        ↓ weights snapshot via SHM versioned slots
M EvalWorker  (periodic eval, EpisodeRunner × LocalNet snapshot)
1 EvalServer    (eval aggregator,详 ./eval.md)
```

**SHALL**:

1. Async mode SHALL spawn 4 类 worker 进程(Actor / InferenceServer /
   Learner / EvalWorker)+ 1 EvalServer 聚合进程;具体数量 N / K / M 由
   cfg 控制。

2. Samples SHALL flow actor → learner via SHM ring buffer
   (paradigm-agnostic 缓冲;具体字段布局 P2 落地)。

3. Weights synchronization SHALL use versioned SHM slots(SHALL 9 in
   主 spec):`latest` slot 给 actors live 同步,
   `snapshot_<eval-id>` slots 给 eval workers 隔离 read(详
   [`./eval.md`](./eval.md))。

4. Actor SHALL tolerate stale weights — 用 N steps 前的权重采样不影响
   收敛(per `memory feedback_stale_weights_ok`)。Learner SHALL NOT
   block on actor weight refresh。

5. Inference server SHALL batch concurrent actor requests up to
   `cfg.infer.max_batch` — server 内部 forward,actors 等结果。

6. Each async collector SHALL implement `sync_weights(network)` —
   `{DMCMultiProcessCollector, CFRAsyncCollector, AZAsyncCollector,
   PPOAsyncCollector}` 各 SHALL 把 `network` 的当前(CPU-detached)权重
   republish 到其 actor 权重通道(`InferenceServer.push_weights` /
   `WeightsSHM.publish_weights`),使 actor 下次读取拿到 version 单调递增
   的新权重。driver 在 train 后 honor `plan.sync_weights` 调此 method
   (§3 #8)。

## 6. PipelineState dataclass

PipelineState 是 driver 持有的全局 state(ckpt 序列化对象)。骨架字
段(P2 定 types + 完整字段集):

- `step` — global training step count
- `iter` — collector iteration count
- `schedule` — ScheduleInfo(详 §7)
- `rng_state` — driver-side RNG state(种子继承自 `meta.seed`)
- `eval_history` — past eval reports(详 [`./eval.md`](./eval.md))
- `buffer_state` — Buffer 持有的 ckpt-able state(详
  [`./protocols.md`](./protocols.md))
- `weights_version` — current weights version(async mode use)
- `paradigm_state` — paradigm-specific opaque dict(P2 定 schema)

**SHALL**:

1. PipelineState SHALL be a `@dataclass`-like immutable per step —
   driver loop 显式重建 / 替换 fields,不允许 in-place mutation。

2. PipelineState SHALL be serializable via standard ckpt format
   (pickle / safetensors / dict;P2 定)— resume 后 driver loop 能从
   pickled state 无缝继续。

## 7. ScheduleInfo

ScheduleInfo 是 `paradigm.step_schedule(state) -> ScheduleInfo` 的返回
值,承载 step-dependent 衰减参数(epsilon / lambda / temperature 等)。

**SHALL**:

1. ScheduleInfo SHALL be paradigm-specific dataclass — 字段不跨
   paradigm 复用(避免 PPO 的 clip 范围影响 AZ 的 temperature)。

2. ScheduleInfo SHALL be computed pure from PipelineState + cfg — 不允许
   `step_schedule` 修改任何外部 state。

3. ScheduleInfo SHALL be passed to Collector + LossComputer per
   iteration — 例如 epsilon 决定 actor 行为,temperature 决定 sampling。

## 8. Cross-references

- Collector / NetworkProvider 接口详 [`./protocols.md`](./protocols.md)
- Eval trigger 与 weights snapshot 协议详 [`./eval.md`](./eval.md)
- Network 结构与 ckpt 落盘对象详 [`./network-sharing.md`](./network-sharing.md)
- Async mode 具体进程协议 + SHM ring 字段布局在 P2
  `unified-training-pipeline` change `design.md` 落地
- Stale weights tolerance → `memory feedback_stale_weights_ok`
- Async pipeline 历史背景 → `memory project_eval_service_global` +
  `memory feedback_eval_service_precheck`
