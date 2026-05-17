---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Pipeline Driver — 主循环 + serial vs async + PipelineState

> 治理 `training-architecture/spec.md` SHALL #7(Pipeline mode dispatch)
> 落地细节。Driver 完全 paradigm-agnostic,paradigm 通过 6 protocol 介入。

## 1. Driver 主循环

`training/core/pipeline.py` 单文件,~150 LOC:

```python
def run_pipeline(cfg: TrainingConfig) -> None:
    state = PipelineState.from_cfg(cfg)
    paradigm = load_paradigm(cfg.meta.paradigm)(cfg.paradigm)
    network = paradigm.make_network(cfg)
    optimizer = paradigm.make_optimizer(network)
    buffer = paradigm.make_buffer(cfg)
    loss_fn = paradigm.make_loss(cfg)
    collector = paradigm.make_collector(cfg, network)
    eval_scheduler = build_eval_scheduler(cfg.eval, network)

    state = checkpoint.maybe_resume(state, cfg, network, optimizer, buffer)

    while not state.done():
        plan = paradigm.step_schedule(state)
        if plan.collect:
            result = collector.collect(plan.n_episodes, _train_provider(network, cfg))
            buffer.push(result.transitions)
            state.log_episode_stats(result.episode_stats)
        if plan.train:
            for _ in range(plan.n_train_batches):
                batch = buffer.sample(plan.batch_size, state.rng)
                loss_out = loss_fn.compute(network, batch)
                _backprop(loss_out, network, optimizer)
                state.log_loss(loss_out)
            _publish_weights(network, state)
        if plan.eval and eval_scheduler.due(state.step):
            eval_scheduler.dispatch(state.step, network)
        state.advance(plan)
        checkpoint.maybe_save(state, cfg, network, optimizer, buffer)

    collector.close()
    eval_scheduler.close()
```

Driver 关心 4 件事:**plan.collect / plan.train / plan.eval / checkpoint**。
Paradigm-specific cadence(on-policy vs off-policy / collect:train ratio /
warm-start phase)全部由 `paradigm.step_schedule()` 返回。

## 2. PipelineState

```python
@dataclass
class PipelineState:
    step: int                        # 全局 step counter
    total_episodes: int
    total_transitions: int
    weights_version: int             # 写入 SHM 的版本号(actors pull 这个)
    rng: np.random.Generator
    metrics: MetricsLogger           # writes metrics.jsonl + TB
    start_wall: float
    cfg: TrainingConfig              # frozen ref

    @classmethod
    def from_cfg(cls, cfg) -> "PipelineState":
        rng = np.random.default_rng(cfg.meta.seed)
        return cls(step=0, total_episodes=0, total_transitions=0,
                   weights_version=0, rng=rng,
                   metrics=MetricsLogger(cfg.artifacts_dir),
                   start_wall=time.monotonic(), cfg=cfg)
```

State + checkpoint 协议详 [`../specs/training-architecture/spec.md`](../specs/training-architecture/spec.md)。

## 3. Serial vs Async mode dispatch

Cfg 字段:

```toml
[pipeline]
mode = "serial"  # or "async"
```

**Serial mode**(smoke / debug / CFR):
- Collector 是 `EpisodeCollector`(单进程)或 `TraversalCollector`(线程池)
- Buffer 是 in-process(`ReplayBuffer` / `ReservoirBuffer` / `RolloutBuffer`)
- 无 inference server,Provider 总是 LocalNetworkProvider
- 适合 smoke + debug + CFR(traversal 性质决定无 multi-actor 收益)

**Async mode**(AZ / DMC production):
- Collector 是 `MultiProcessActorCollector`,内部 spawn N actor process
- Buffer 是 `SHMRingBuffer`,actor 直接写,learner 只 sample
- Inference 可选 Remote(K server)或 Local(每 actor 持 copy)
- 进程拓扑详 [`./async-pipeline.md`](./async-pipeline.md)

Driver loop 形式完全相同;差异在 collector 内部实现。

## 4. StepPlan

```python
@dataclass
class StepPlan:
    collect: bool
    n_episodes: int                  # 0 if not collect
    train: bool
    n_train_batches: int             # 0 if not train
    batch_size: int                  # paradigm-specific
    eval: bool                       # 让 driver check scheduler due
    advance_step: int                # 通常 = 1,allow paradigm 跳过
```

示例 paradigm cadence:
- AZ:1000 episodes collect → 100 train batches(ratio 10:1)
- DMC:async actor 连续 collect,learner 异步 sample → train = True 每 step
- PPO:rollout 2048 transitions → 4 epochs × N minibatch train → buffer.clear
- CFR:1 outer iter = K traversal + advantage fit + strategy fit
- BC:无 collect step(dataset 已 ready),train 直到 epoch 完

## 5. Checkpoint 协议

```python
checkpoint.maybe_save(state, cfg, network, optimizer, buffer)
```

写到 `cfg.artifacts_dir/ckpt_step{step}.pt`,内容:
- `network.state_dict()`
- `optimizer.state_dict()`
- `state.rng.bit_generator.state`
- `state.step / total_episodes / total_transitions / weights_version`
- `buffer` snapshot(可选;仅 BC / on-policy)
- cfg snapshot(detect cfg drift on resume)

Cfg `[checkpoint] save_every = 1000` 控制频率。`maybe_resume` 读最新 ckpt
+ verify cfg hash + restore RNG。详 `training/core/checkpoint.py`。

## 6. Cross-references

- Protocols 详细 → [`./core-protocols.md`](./core-protocols.md)
- Async 拓扑详 → [`./async-pipeline.md`](./async-pipeline.md)
- Eval scheduler → [`./episode-runner.md`](./episode-runner.md)
- 主 spec → [`../../../specs/training-architecture/pipeline.md`](../../../specs/training-architecture/pipeline.md)
