---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: search-parallel
subtopic: topology
---

# Topology — 进程拓扑 + worker / main 改造点

> 本 subtopic 锚定 GICG self-play 并行架构的进程拓扑 — 三进程类型
> (trainer main + inference server + N workers)的职责划分、worker
> 内 MCTS kernel 改造点、main 内异步流水(ingest + train)调度。IPC
> 消息协议见 [`./protocols.md`](./protocols.md);inference server 内部见
> [`./inference-server.md`](./inference-server.md)。

## 1. 进程拓扑

```
┌─────────────┐        ┌────────────────────┐
│  main       │──weights──>│ inference server │<──eval──┐
│             │        │ (持 NN, batch)     │         │
│ train loop  │<─trajectory──┐                          │
│ arena       │              │                          │
│ gauntlet    │              │                          │
│ buffer      │              │                          │
└─────────────┘              │                          │
                             │                          │
                    ┌────────┴──────────┐               │
                    │ worker 0..N-1     │───────────────┘
                    │  MCTS tree only   │   (leaf eval RPC)
                    │  env step         │
                    │  determinization  │
                    └───────────────────┘
```

### 1.1 SHALL invariants

1. Training SHALL run as 3 process types:
   - **Trainer main**(1 proc):buffer + train_step + arena/gauntlet 调度 + launcher
   - **Inference server**(1 proc):持 NN weights + 动态 batching + hook_emb cache
   - **Self-play workers**(N proc):MCTS tree + env step + 确定化采样
2. Worker SHALL NOT 持 network weights — leaf eval 必经 server。
3. Trainer main + inference server 各持一份 weights:Main 始终最新
   (供 arena/gauntlet 评估用),Server 可能落后 K train steps(供
   self-play 采样用)。详 [`./inference-server.md`](./inference-server.md) §3
   stale weights 容忍。
4. 进程间通信 SHALL use OS-level IPC(`multiprocessing.Pipe` v1),
   SHALL NOT share Python objects via shared memory(防 GIL 串行化)。
5. 启动顺序 SHALL be:trainer main → spawn inference server → spawn N
   workers → workers connect server via pipe handles。

## 2. Trainer main 进程职责

### 2.1 SHALL hold

- ReplayBuffer(唯一一份,在主进程内)
- 本地 `Agent`(始终最新 weights,供 arena/gauntlet)
- train loop(独立消费 buffer,不等 worker)
- ingest thread + train thread 双线程(异步流水)

### 2.2 SHALL responsibilities

1. **Train loop**(独立节拍):
   - 当 `len(buffer) ≥ min_buffer` 时,从 buffer 采 batch + `train_step`
   - 每 `train_step_per_push` 次 push 一次 CPU `state_dict` 给 server
   - 不等 server ACK,直接继续训练
2. **Ingest loop**(drain worker trajectory):
   - 从 `result_queue` 收 trajectory(`worker → main` channel)
   - 放入 buffer + 递增 `games_completed` 计数
3. **Arena / Gauntlet**(train thread 内调度):
   - 每 `games_per_arena` 局触发 arena;每 `games_per_gauntlet` 局触发 gauntlet
   - **不走 server**,用 local agent(详 [`./inference-server.md`](./inference-server.md) §4)
   - 触发条件用 ingest thread 更新的 `games_completed`,train thread
     读;简单 `threading.Event` / 原子 int 即可

### 2.3 双线程伪代码

**Train thread**(主进程内):
```python
while not stop:
    if len(buffer) >= min_buffer:
        for _ in range(train_steps_per_tick):
            batch = buffer.sample(...)
            train_step(agent, batch, ...)
        if train_tick % push_interval == 0:
            server.push_weights(cpu_state_dict(agent))
    else:
        sleep(10ms)
```

**Ingest thread**(主进程内):
```python
while not stop:
    res = result_queue.get()
    buffer.add_trajectory(res.game_static, res.steps)
    games_completed += 1
    if games_completed >= n_games:
        stop = True
```

### 2.4 Dispatch 模型

1. SHALL be **one-shot at launch**:开局时直接派 `n_games` 个 play
   命令给 worker pool。
2. Worker 完一局自己结束,SHALL NOT need main to re-dispatch — 简化
   流水控制,避免 main 成为 dispatch 瓶颈。

## 3. Inference server 进程职责

### 3.1 SHALL hold

- 一份 network weights(可能比 main 落后 K train steps)
- hook_emb cache(per `(worker_id, game_id)`)
- 两个独立 queue:eval request queue + weight update queue

### 3.2 SHALL responsibilities

1. Pre-encode static obs(GameStart 时 hook_emb + card_emb 编码,缓存)
2. Serve `eval` RPC(动态 batching:`max_batch_size` / `batch_timeout_ms`)
3. Apply weight updates **between batches**(不打断正在飞的 forward)
4. Free cache entry on GameEnd(显式剔除;worker 崩溃时 v1 不做心跳清理)

详 [`./inference-server.md`](./inference-server.md)。

## 4. Worker 进程职责与改造点

### 4.1 SHALL hold

- MCTS tree(每局新建,局结束释放)
- `GicgEnv` 实例(env step + 确定化采样)
- `inference_client`(轻量 RPC client,持 pipe 句柄到 server)

### 4.2 SHALL NOT hold

- Network weights(全部走 server)
- ReplayBuffer(单一在 main)

### 4.3 MCTS kernel 改造点

唯一一处改动:`training/az/mcts/rollout.py::_eval_leaf`

```python
# 之前:
prior, v = agent.eval_state(static, dyn, refs, payments)

# 之后:
prior, v = inference_client.eval(static_key, dyn, refs, payments)
```

### 4.3.1 SHALL invariants

1. `inference_client.eval` SHALL be synchronous(发送 + 阻塞等回复),
   保持 MCTS 树循环不变。
2. MCTS select / expand / backprop SHALL NOT change — 仅 leaf eval
   入口替换。
3. `static_key = (worker_id, game_id)` SHALL identify the cached
   hook_emb on server。

### 4.4 Game lifecycle

Worker 开局时:
```python
client.game_start(game_id, game_static)  # server 缓存 hook_emb
for move in game:
    mcts_search(...)   # 内部触发 N 次 client.eval
    env.step(...)
client.game_end(game_id)
result_queue.put(trajectory)
```

#### 4.4.1 SHALL invariants

1. Worker SHALL call `client.game_start(game_id, game_static)` 局开始
   一次 — 上传 `hooks / counters / cards` 静态数据给 server 编码缓存。
2. Worker SHALL call `client.game_end(game_id)` 局结束一次 — 触发
   server 释放缓存条目。
3. Worker SHALL push `trajectory` to main's `result_queue` 局结束后 —
   结构与现有 `parallel_selfplay.py` 一致,`ParallelSelfPlayPool` 的
   `_ResultShim` 路径可直接复用。

## 5. 增量实现顺序

按可独立测试的边界 SHALL implement in order:

1. **InferenceServer 最小骨架**:单 worker,同步 batch=1,跑通
   game_start / eval / game_end / stop 协议。对比本地 `agent.eval_state`
   结果数值一致
2. **Dynamic batching**:加 `max_batch` + `timeout`,并发 2-4 worker
   测吞吐
3. **Weight sync**:加 weight_update 协议,独立 queue,数值测试
   (push 后下一次 eval 结果应该变)
4. **Worker 改造**:MCTS kernel 换 `inference_client.eval`,端到端
   4 worker smoke
5. **Async main**:ingest / train 拆线程,arena/gauntlet 走 local agent
6. **基准测试**:c1-scale,`n_workers ∈ {1, 4, 8}` × 开/关 async
7. **替换 `parallel_selfplay.py`**:老实现保留到新的通过 10 局
   c1-scale 测试后再删
8. **文档更新**:`docs/1_specs/training/az_loop.md` 加架构小节,
   `implementation.md` 勾上

## 6. 开放问题(死锁 / 失败恢复)

### 6.1 死锁风险

- **场景**:Worker 发 eval 请求 → server 暂停等 batch 凑齐 → 同时 main
  在 push weights → server 卡在 `load_state_dict` → worker 超时
- **解法**:Weight update SHALL only be applied **between batches**,
  不打断正在飞的 batch forward(SHALL invariant 6 in [`./spec.md`](./spec.md))
- 详细调度见 [`./inference-server.md`](./inference-server.md) §3。

### 6.2 失败恢复(v1)

1. **Worker 崩溃**:server 持有的 cache 条目永远悬挂(v1 忽略,C1 规模
   worker 不会崩太多)。
2. **Server 崩溃**:worker 全部卡住 → main 检测 heartbeat 超时 →
   fail-fast 整个 run。
3. **v1 策略**:任何异常均整体 raise + 停机,SHALL NOT 做部分恢复。
4. 未来若加入 failover,SHALL go through OpenSpec change(当前明确
   非目标,见 [`./spec.md`](./spec.md) §6)。

## 7. Cross-references

- [`./protocols.md`](./protocols.md) — 三 channel IPC 消息协议
- [`./inference-server.md`](./inference-server.md) — server 内部动态
  batching / hook_emb cache / weight update 细节
- [`../search-ismcts/algorithm.md`](../search-ismcts/algorithm.md) —
  MCTS 算法本体(worker 内运行)
- [`../network-architecture/training-pipeline.md`](../network-architecture/training-pipeline.md) —
  network 视角的 trainer pipeline(train_step / loss / backward)
- [`../training-architecture/pipeline.md`](../training-architecture/pipeline.md) —
  paradigm-agnostic driver loop(本 subtopic 是 driver 的 inner loop)
