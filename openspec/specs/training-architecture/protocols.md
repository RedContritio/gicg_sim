---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: protocols
---

# Protocols — paradigm-agnostic 接口契约

> 本 subtopic 锚定 `training/core/protocols.py` 内 6 个核心 protocol
> 的方向与硬约束。详细方法签名(参数类型 / 返回值 / 异常)在 P2
> `unified-training-pipeline` change 落地。骨架阶段仅列方法名 + 一行用
> 途注释。

## 1. Scope

本 subtopic 覆盖 6 个 protocol:

- **Paradigm** — paradigm 入口,提供 component factories
- **Collector** — 训练数据采集(env episode / dataset / replay)
- **Buffer** — 训练样本存储与采样
- **LossComputer** — 训练 loss 计算
- **EpisodePolicy** — 单局内决策与 finalize
- **NetworkProvider** — 推理接口抽象(local / remote × device)

## 2. Paradigm protocol

`Paradigm` 是 paradigm-agnostic driver 与 paradigm-specific 实现之间唯
一的 entry point。Driver loop 仅依赖 Paradigm 接口,不直接 import 任何
paradigm 模块。

**核心 SHALL**:

1. Each paradigm SHALL provide a `Paradigm` implementation registered
   under a unique `meta.paradigm` key(`"az"` / `"dmc"` / `"cfr"` /
   `"ppo"` / `"bc"`)。

2. Paradigm protocol SHALL expose 6 factory methods(详细签名 P2 定):
   - `make_network(cfg) -> nn.Module` — 构造 paradigm-specific 网络
   - `make_collector(cfg, network, ...) -> Collector` — 构造采集器
   - `make_buffer(cfg) -> Buffer` — 构造训练样本存储
   - `make_loss(cfg) -> LossComputer` — 构造 loss 计算
   - `make_optimizer(cfg, network) -> Optimizer` — 构造 optimizer
   - `step_schedule(state) -> ScheduleInfo` — paradigm-specific 调度
     (epsilon / lambda / temperature 等的 step-dependent 衰减)

3. Paradigm SHALL be **stateless** — 全部 state 落 `PipelineState`
   (详 [`./pipeline.md`](./pipeline.md));paradigm instance 本身只持
   有 cfg,跨进程 pickle-safe。

4. Paradigm registry SHALL live in `training/core/registry.py`,新
   paradigm 注册 SHALL 走 OpenSpec change(新 paradigm dossier)。

## 3. Collector protocol

Collector 负责产生训练样本。不同 paradigm 来源不同:env episode rollout
(AZ / PPO / DMC)、replay parsing(CFR traversal)、static dataset
(BC)。Driver loop 只调统一接口。

**核心 SHALL**:

1. Collector SHALL expose `collect(n_samples) -> Iterable[Sample]` 接口
   (具体 Sample 类型 P2 定,paradigm-specific)。

2. Collector SHALL be self-contained 对并行 — serial mode 单进程同步运
   行,async mode 内部派生 N actor 子进程。Driver loop SHALL NOT know
   parallelism 细节。

3. Collector SHALL produce paradigm-agnostic Sample objects(driver 透
   传给 Buffer / LossComputer)— 不允许 cross-paradigm Sample 混用。

4. Env-driven collectors SHALL use `EpisodeRunner`(详
   [`./eval.md`](./eval.md))与 `EpisodePolicy`(本文件 §6)— 不允
   许 reimplement episode loop。

## 4. Buffer protocol

Buffer 负责训练样本存储与采样。不同 paradigm 策略差异大(AZ FIFO replay
/ CFR reservoir / DMC dedup / BC static dataset)。

**核心 SHALL**:

1. Buffer SHALL expose `push(samples)` 与 `sample(batch_size) -> Batch`
   接口(具体 Batch 类型 P2 定)。

2. Buffer SHALL be paradigm-specific 内部策略 — driver 仅按 cfg 配置
   阈值 trigger sample;采样策略(FIFO / reservoir / dedup / shuffle)
   由 paradigm 决定。

3. Buffer SHALL be ckpt-able — 状态可序列化写盘,resume 后 push /
   sample 行为与中断前一致。详 [`./pipeline.md`](./pipeline.md)
   ckpt 协议。

4. On-policy paradigm(e.g. PPO)SHALL 在 `step_schedule` 返回 `StepPlan`
   时显式 set `clear_buffer_after_train=True` 声明 per-iter clear intent。
   Driver SHALL honor 此 flag,在 train block 结束后(eval / ckpt 之前)
   调用 `buffer.clear()`。Off-policy / dataset-driven paradigm SHALL 保留
   default `False`(无 clear 副作用)。**Rationale**:Buffer 是 paradigm-
   agnostic storage 抽象,clear 时机决策权归 paradigm。**Failure mode
   if violated**:PPO 第 2 outer iter `collect` push 时 buffer 仍持有
   第 1 iter transitions → `RolloutBuffer.push: over capacity` raise(per
   `paradigm-ppo/spec.md` § P4.1 on-policy invariant)。Wired by
   `ppo-buffer-clear-orchestration` archive 2026-05-17。

## 5. LossComputer protocol

LossComputer 负责单 batch 的训练 loss 计算。Optimizer 与 backward 由
driver 持有。

**核心 SHALL**:

1. LossComputer SHALL expose `compute(network, batch) -> dict[str,
   Tensor]` 接口,返回命名 loss components(供 logging + sum)。

2. LossComputer SHALL be pure — 不持有 mutable state(running stats /
   epsilon decay 等放 ScheduleInfo);跨 batch 独立。

3. LossComputer SHALL handle paradigm-specific loss(AZ KL+MSE / CFR
   advantage MSE / DMC MSE / PPO clip+VF+entropy / BC CE)详 paradigm
   dossier(P2 落地)。

## 6. EpisodePolicy protocol

EpisodePolicy 是单 episode 内的决策接口,actor 与 eval worker 共用 — 通
过它把 paradigm-specific 决策(MCTS search / argmax Q / sample logits /
avg policy mix)塞进 paradigm-agnostic EpisodeRunner。

**核心 SHALL**:

1. EpisodePolicy SHALL expose 2 方法:
   - `act(state, mask) -> action` — 单步决策
   - `finalize_episode(trajectory) -> Iterable[Sample]` — episode 结
     束后产生训练样本(MCTS visit count / TD target / regret 等)

2. EpisodePolicy SHALL be constructed with one NetworkProvider — placement
   / device 由 NetworkProvider 抽象屏蔽。

3. EpisodePolicy SHALL be **deterministic** when configured with
   `deterministic=True`(eval mode) — 不允许 hidden randomness 与
   `epsilon=0` 同时还出非确定输出。

## 7. NetworkProvider protocol

NetworkProvider 抽象 inference 调用,屏蔽 Placement(local / remote)×
Device(cpu / mps / cuda)二维差异。

**核心 SHALL**:

1. NetworkProvider SHALL expose `infer(obs_batch) -> outputs` 接口。具
   体 outputs 形态 paradigm-specific(policy logits / Q / value)。

2. Two placement modes SHALL be supported,both 实现 NetworkProvider 接
   口:
   - `LocalNetworkProvider` — 本进程持有 nn.Module,direct forward。
     Device 由 cfg 指定,可任意 PyTorch device。
   - `RemoteNetworkProvider` — 走 IPC(Unix socket / SHM)调远端
     inference server。Server 自身用 LocalNetworkProvider。

3. Placement × Device SHALL fully orthogonal — Remote 模式 server 端可
   选任意 device;Local 模式同样可选任意 device。

4. NetworkProvider SHALL expose `update_weights(state_dict | version)`
   接口 — Local 直接 load_state_dict;Remote 通过 IPC 信号 + SHM 版本
   slot(详 [`./pipeline.md`](./pipeline.md) + [`./eval.md`](./eval.md))。

## 8. Cross-references

- Pipeline driver 与 protocol 的交互详 [`./pipeline.md`](./pipeline.md)
- Network sharing(encoder + heads)详 [`./network-sharing.md`](./network-sharing.md)
- EpisodeRunner 与 EpisodePolicy 协作详 [`./eval.md`](./eval.md)
- OpponentRegistry 通过 NetworkProvider 加载 historical opponent 详
  [`./opponent-mix.md`](./opponent-mix.md)
- 详细方法签名 + 类型在 P2 `unified-training-pipeline` change `design.md`
  落地
