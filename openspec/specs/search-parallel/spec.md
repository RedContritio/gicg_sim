---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: search-parallel
---

# Search Parallel — 并行推理服务器 + 异步训练流水

> 本 capability spec 治理 GICG self-play 的并行推理与异步训练流水
> 架构 — 推理集中化(动态 batch)+ self-play / training 异步脱钩 +
> 跨 worker 共享 inference server。本 spec 治理**进程拓扑 + IPC 协议**;
> 算法本体(IS-MCTS 选择 / 扩展 / 回传)由 [`search-ismcts`](../search-ismcts/spec.md)
> 治理。
>
> 本 spec 从 `docs/1_specs/search/parallel.md`(390 行)抽取规约,
> SHALL 化 + 按 3 subtopic 拆分。实测性能 / MPS GPU 失败 / C1 验证
> run 耗时估算 → `docs/5_history/search_history.md`(P1-T3 mv)。

## 1. Purpose

GICG self-play 并行架构需被规约化,否则会出现:

- 原 `parallel_selfplay.py` worker-per-agent 架构(每 worker 持完整网络)
  在 d_model=64 / 4 worker 下加速比仅 2.54×(理想 4×),根因是每个
  worker batch=1 推理 + 互抢 CPU + 带宽。新 paradigm 不知契约会重蹈
- Inference server 动态 batching 的关键不变量(动态 batch + timeout 协议、
  hook_emb 缓存复用)在跨 paradigm 共享时静默偏离
- Async 流水的正确性契约(stale weights 上界、weight push / batch
  forward 互斥防死锁)在 refactor 中被破坏
- Arena / Gauntlet 评估路径的"不走 server"决策(确保评估用确定版本
  weights)被误改成走 server,导致评估随机化

本 spec 提供 3 大类约束:

- **Process topology**(详 [`./topology.md`](./topology.md))— main / inference server / N workers + worker / main 改造点
- **IPC protocols**(详 [`./protocols.md`](./protocols.md))— worker ↔ server / main ↔ server / worker ↔ main 三 channel 消息协议
- **Inference server**(详 [`./inference-server.md`](./inference-server.md))— 动态 batching / hook_emb 缓存 / 权重更新 / arena 不走 server

## 2. Scope

**In scope**:

- 三进程类型拓扑(main + inference server + N workers)
- 三 channel IPC 协议(worker → server eval / main → server weight /
  worker → main trajectory)
- Inference server 内部:动态 batching、hook_emb 缓存、weight queue、
  Pipe transport
- Main 异步流水:ingest thread + train thread + arena/gauntlet 调度
- Worker 改造点:MCTS kernel `_eval_leaf` 接 `inference_client.eval`
- 增量实现顺序与回滚边界

**Out of scope**:

- IS-MCTS 算法本体(选择 / 扩展 / 回传 / N_avail)— 由
  [`search-ismcts`](../search-ismcts/spec.md) 治理
- 网络结构(value / policy head,encoder)— 由
  [`network-architecture`](../network-architecture/spec.md) 治理
- Driver / buffer / opponent mix 顶层骨架 — 由
  [`training-architecture`](../training-architecture/spec.md) 治理
  (本 spec 是 network 视角的 RPC 细节)
- 跨机分布式训练(localhost only,见 §6 非目标)
- GPU 加速决策 — 历史结论:d_model=64 下 MPS 3-4× 慢于 CPU,详
  [`docs/5_history/search_history.md`](../../../docs/5_history/search_history.md)
- 完全对等分布式 / Worker 热添加 / Server failover(均明确非目标,
  见 §6)

## 3. Core SHALL invariants

以下 8 条 invariant 是本 capability 的硬约束。任意冲突应作为 OpenSpec
change 提案修订,而非在代码中静默偏离。

1. **三进程类型拓扑**:Self-play SHALL run as 3 process types — 1
   trainer main + 1 inference server + N self-play workers。Worker
   SHALL NOT 持 network weights;Main + Server 各持一份(Main 始终
   最新,Server 可能落后 K train steps)。详 [`./topology.md`](./topology.md) §1。

2. **Centralized inference**:Workers SHALL query inference server via
   RPC for leaf eval — `_eval_leaf` 内部由 `inference_client.eval(...)`
   替代直接 `agent.eval_state(...)`。MCTS 树逻辑(select / expand /
   backprop)SHALL NOT change。详 [`./topology.md`](./topology.md) §3。

3. **Dynamic batching**:Inference server SHALL collect requests up to
   `max_batch_size` or `batch_timeout_ms` and forward once per batch。
   `max_batch_size` 与 `batch_timeout_ms` SHALL be cfg-driven(初值
   32 / 3ms,可调)。详 [`./inference-server.md`](./inference-server.md) §1。

4. **hook_emb cache**:Inference server SHALL cache `(hook_emb,
   card_emb)` per `(worker_id, game_id)` keyed entry — 局开始 GameStart
   编码缓存,局结束 GameEnd 显式剔除。SHALL NOT 跨局复用(防 stale
   embedding 污染)。详 [`./inference-server.md`](./inference-server.md) §2。

5. **Stale weights bounded**:Worker SHALL tolerate stale weights up to
   bounded interval(`train_step_per_push × train_steps_per_game ×
   avg_game_time`,典型 10-30 局)。Stale weights 在标准 AZ 工程实践
   (Lc0 / ELF OpenGo)被验证不影响收敛,**无需额外算法近似标注**。
   详 [`./inference-server.md`](./inference-server.md) §3。

6. **Weight update non-preemptive**:Weight update SHALL only be
   applied between batches — 不打断正在飞的 batch forward。Weight
   queue SHALL be **independent** from eval queue(防互相阻塞)。
   详 [`./inference-server.md`](./inference-server.md) §3。

7. **Arena / Gauntlet bypass server**:Arena 与 Gauntlet evaluation
   SHALL use trainer main's local agent(始终最新 weights),SHALL NOT
   route through inference server。理由:评估需用确定版本 weights
   防比较污染;arena/gauntlet 频率低,吞吐不敏感;避免评估流量打乱
   self-play batch 节奏。详 [`./inference-server.md`](./inference-server.md) §4。

8. **Three-channel IPC**:IPC SHALL be split into 3 distinct channels —
   `worker → server`(eval RPC)/ `main → server`(weight update)/
   `worker → main`(trajectory result)。Transport v1 SHALL use
   `multiprocessing.Pipe`(per-worker pipe,server 用
   `connection.wait(pipes, timeout)` 收集请求);Queue(A)与 SHM ring
   buffer(C)为可选升级路径。详 [`./protocols.md`](./protocols.md) §1。

## 4. Subtopics

本 capability 由本文件 + 3 个 subtopic 组成。每个 subtopic 专注一组
正交规则,主 spec.md 只列 SHALL invariant 概要,细节落 subtopic。

- [Topology](./topology.md) — 三进程类型职责(main / inference
  server / N workers)、worker 改造点(`_eval_leaf` + game lifecycle)、
  main 改造点(ingest thread + train thread + arena/gauntlet)、
  Dispatch 模型
- [Protocols](./protocols.md) — 三 channel IPC 协议(eval / weight /
  trajectory)+ 消息字段定义(GameStart / Eval / GameEnd /
  WeightUpdate / Trajectory)+ Transport 选型与升级路径
- [Inference server](./inference-server.md) — 动态 batching 算法 + hook_emb
  缓存语义 + 权重更新调度 + Arena/Gauntlet bypass 决策 + 失败恢复

## 5. Cross-references

**Sibling capability specs**:

- [`openspec/specs/search-ismcts/`](../search-ismcts/spec.md) — IS-MCTS
  算法本体(本 spec 治理进程拓扑,search-ismcts 治理算法语义)
- [`openspec/specs/network-architecture/`](../network-architecture/spec.md) —
  网络结构 + training pipeline(本 spec 的 RPC 字段与
  [`training-pipeline.md`](../network-architecture/training-pipeline.md)
  衔接)
- [`openspec/specs/training-architecture/`](../training-architecture/spec.md) —
  paradigm-agnostic training infra(本 spec 是 network 视角的 RPC 细节;
  driver / opponent mix / buffer 顶层骨架在 training-architecture)
- [`openspec/specs/training-architecture/protocols.md`](../training-architecture/protocols.md) —
  NetworkProvider Remote 部分(本 spec 的 worker → server RPC 与之对齐)
- [`openspec/specs/openspec-policy/`](../openspec-policy/spec.md) —
  本 spec 的格式与阈值由其治理

**History / postmortems**:

- [`docs/1_specs/search/parallel.md`](../../../docs/1_specs/search/parallel.md) —
  本 spec 的 narrative source,已加 deprecation note,保留至 P1++
  整体清理
- [`docs/5_history/search_history.md`](../../../docs/5_history/search_history.md) —
  实测性能(虚损失 par=4 1.94× / par=8 持平)/ MPS GPU 失败
  (d_model=64 下 3-4× 慢于 CPU)/ C1 验证 run 耗时估算(2000 局 4
  worker par=4 ~6.6h)

## 6. 非目标

以下明确不在本 capability 范围:

- 完全对等的分布式训练(single machine only)
- 跨机 RPC(localhost pipe only)
- Trajectory 的 zero-copy 传输(先用 pickle,测过再优化)
- Worker 热添加 / 动态扩缩(固定 `n_workers` 启动时定)
- 推理 server 的 failover(崩了就整体重启 run)

未来若需放开任一项 SHALL go through OpenSpec change。

## 7. Status

- **Created**:2026-05-15(P1-T3)
- **Version**:0(初始落地)
- **Source**:`docs/1_specs/search/parallel.md`(390 行)
- **Expected revision triggers**:
  - GPU inference server 上线(d_model ≥ 256 或 batch ≥ 64)
  - Transport 升级到 SHM ring buffer(若 pipe pickle 占比 > 15%)
  - 多 inference server 进程(突破单 server 吞吐天花板)
  - 跨机分布式开启(非目标 reopen)
