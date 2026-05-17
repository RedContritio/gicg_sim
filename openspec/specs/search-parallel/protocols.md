---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: search-parallel
subtopic: protocols
---

# Protocols — IPC 消息协议(eval / weight / trajectory)

> 本 subtopic 锚定 GICG self-play 并行架构的三 channel IPC 协议 —
> worker → server eval RPC、main → server weight update、worker → main
> trajectory result。进程拓扑见 [`./topology.md`](./topology.md);server
> 内部见 [`./inference-server.md`](./inference-server.md)。

## 1. 三 channel 拓扑

```
              main ──[weight queue]──> server
                                          ↑
worker[0..N-1] ──[per-worker pipe]────────┘     (eval RPC)
       │
       └──[result_queue]──> main                (trajectory)
```

### 1.1 SHALL invariants

1. IPC SHALL be split into 3 distinct channels:
   - **Worker → Server**(eval RPC,bidirectional 在同一 pipe)
   - **Main → Server**(weight update,one-way)
   - **Worker → Main**(trajectory result,one-way)
2. Three channels SHALL NOT share the same queue/pipe — 防 weight
   update 阻塞 eval 或 vice versa。
3. Each worker SHALL have its own dedicated pipe to server(per-worker
   pipe);server 用 `multiprocessing.connection.wait(pipes, timeout)`
   收集请求,天然契合动态 batching。
4. Transport v1 SHALL use `multiprocessing.Pipe`(选项 B):pickle 开销
   比 Queue(A)小,比 SHM(C)实现简单。测出 pipe pickle 占比 > 15%
   再升级 SHM。

## 2. Worker → Server: eval RPC

每个 worker 持一条 pipe 到 server。生命周期协议有 3 种消息。

### 2.1 GameStart(每局开始一次)

```python
{"kind": "game_start",
 "worker_id": int, "game_id": int,
 "game_static": dict}          # hooks, counters, cards
```

#### 2.1.1 SHALL invariants

1. Worker SHALL send `game_start` 局开始一次,**before** 任何 `eval`
   请求。
2. `game_static` SHALL contain everything needed for server to encode
   hook_emb + card_emb — 由 `gicg_env` 的 `GameGetStaticObs` 提供
   (详 [`../network-architecture/obs.md`](../network-architecture/obs.md))。
3. Server SHALL respond with ACK after caching hook_emb(同步等待 ACK
   后 worker 才能发送 `eval`)。
4. `game_id` SHALL be monotonically increasing per worker(防 cache
   key 冲突)。

### 2.2 Eval(每次 rollout leaf)

```python
{"kind": "eval",
 "worker_id": int, "game_id": int,
 "dyn": dict, "refs": list, "payments": list,
 "req_id": int}
```

Server 查缓存拿 hook_emb,跑 cross-attn + 头部,返回:
```python
{"req_id": int,
 "prior": np.ndarray,          # shape=(n_legal,)
 "value": float}
```

#### 2.2.1 SHALL invariants

1. Worker SHALL send one `eval` request per MCTS leaf — 同步阻塞等
   `prior` + `value` 返回。
2. `req_id` SHALL be unique per worker(monotonic counter)— server
   echo back 供 worker 匹配回复。
3. `dyn` SHALL contain dynamic obs(counter values / hand 内容 /
   dice 等),由 `gicg_env` 的 `GameGetDynamicObs` 提供。
4. `refs` SHALL contain legal action refs(skill/card refs);`payments`
   SHALL contain对应 dice payment 多重集。
5. `prior` 数组维度 SHALL equal `len(refs)`(per-legal-action 先验)。
6. `value` SHALL be a scalar in `[-1, 1]`(tanh 输出,详
   [`../network-architecture/heads.md`](../network-architecture/heads.md))。

### 2.3 GameEnd(每局结束一次)

```python
{"kind": "game_end", "worker_id": int, "game_id": int}
```

#### 2.3.1 SHALL invariants

1. Worker SHALL send `game_end` 局结束一次,触发 server 释放对应
   cache 条目。
2. After `game_end`,worker SHALL NOT send any `eval` with the same
   `(worker_id, game_id)` — server 已剔除缓存,会 raise。
3. Worker 崩溃时不发 `game_end`,server cache 条目永远悬挂(v1 忽略,
   详 [`./topology.md`](./topology.md) §6.2)。

## 3. Main → Server: weight update

```python
{"kind": "weight_update", "weights": cpu_state_dict, "version": int}
```

### 3.1 SHALL invariants

1. Weight update SHALL go through an **independent queue**(不与 eval
   request queue 共用)— 防互相阻塞。
2. `weights` SHALL be CPU `state_dict`(non-CUDA tensors)— 序列化
   开销小,server 端 load 无需 device 转移。
3. `version` SHALL be monotonically increasing(用于日志 / 调试,
   diagnosing 收敛性);non-essential to correctness。
4. Main SHALL NOT wait for ACK after push — fire-and-forget,继续
   train loop。
5. Server SHALL apply weight update **between batches**(SHALL NOT
   preempt in-flight batch forward)— 详
   [`./inference-server.md`](./inference-server.md) §3。

## 4. Worker → Main: trajectory result

### 4.1 SHALL invariants

1. Trajectory format SHALL be backward compatible with existing
   `parallel_selfplay.py::result_queue` — 结构不变,`ParallelSelfPlayPool`
   的 `_ResultShim` 路径直接复用。
2. Trajectory SHALL contain:
   - `game_static`(供 buffer 重建 obs)
   - `steps`(list of `(obs_dyn, action_idx, mcts_visits, z)`)
   - `outcome`(P0 视角的 z ∈ `{-1, 0, +1}`)
3. Trajectory SHALL be pickled via `multiprocessing.Queue`(v1)。
   Zero-copy 升级(SHM)是明确非目标(详 [`./spec.md`](./spec.md) §6)。

## 5. Transport 选型

### 5.1 Options

- **A**:`mp.Queue`(pickle 每次)— 简单,每次 RPC pickle/unpickle 约
  50-100µs,可接受
- **B**:Per-worker `mp.Pipe` — **v1 选 B**;双向,server 用
  `multiprocessing.connection.wait` 轮询所有 pipe,天然契合动态 batching
- **C**:Shared memory ring buffer + semaphore — 最快,复杂度高,测出
  pipe pickle 占比 > 15% 再升级

### 5.2 SHALL invariants

1. v1 SHALL use **option B**(per-worker pipe)。
2. Server SHALL use `multiprocessing.connection.wait(pipes, timeout=
   batch_timeout_ms)` 收集请求,SHALL NOT busy-poll 单 pipe。
3. 升级到 SHM(选项 C)SHALL go through OpenSpec change — 当前明确
   推迟,触发条件 "pipe pickle 占比 > 15%" 详
   [`./spec.md`](./spec.md) §7。

## 6. Cross-references

- [`./topology.md`](./topology.md) — 三进程类型职责与改造点
- [`./inference-server.md`](./inference-server.md) — server 内部
  batching / cache / weight 调度
- [`../network-architecture/training-pipeline.md`](../network-architecture/training-pipeline.md) —
  network 视角的 RPC 字段语义(static vs dynamic obs schema)
- [`../training-architecture/protocols.md`](../training-architecture/protocols.md) —
  NetworkProvider Remote 接口(本 subtopic 的 worker → server RPC 与之
  对齐)
