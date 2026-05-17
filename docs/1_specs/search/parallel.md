# 并行推理服务器 + 异步训练流水

> **MOVED to `openspec/specs/search-parallel/`**（2026-05-15，P1-T3）
>
> 本文档内容已迁到 OpenSpec（SHALL 语言），按 3 subtopic 拆分:
> - [Topology](../../../openspec/specs/search-parallel/topology.md) — 三进程类型 + worker / main 改造点
> - [Protocols](../../../openspec/specs/search-parallel/protocols.md) — 三 channel IPC 消息协议
> - [Inference server](../../../openspec/specs/search-parallel/inference-server.md) — 动态 batching / hook_emb 缓存 / 权重更新 / arena 旁路
> - 顶层 spec:[search-parallel/spec.md](../../../openspec/specs/search-parallel/spec.md)
>
> 历史叙事（实测性能 / MPS GPU 失败 / C1 验证 run 耗时估算）→ [`docs/5_history/search_history.md`](../../5_history/search_history.md)
>
> 本文件保留至 P1++（`docs/1_specs/` 整体清理）；**只读**。

---

> 本文档对应[决策日志](decisions.md)中的方案 B + C。替换现有
> `parallel_selfplay.py` 的 worker-per-agent 架构,把 NN 推理集中化、
> selfplay/training 完全异步化。
>
> 本文讲**进程/IPC 架构**（worker pool、inference server、虚损失 batching）。
> 训练算法流程（selfplay → buffer → train → arena）见
> [`training_loop.md`](training_loop.md)。

## 背景

当前的多进程 self-play(`parallel_selfplay.py`)把一个 `Agent`(含
完整网络)复制到每个 worker,worker 各自做 MCTS + 推理,主进程串行
训练 + arena + gauntlet。在 c1-scale(d_model=64, 400 rollouts/move)
下实测:

- serial: 43.4s / game
- 4 worker: 17.1s / game
- **加速比 2.54×**(理想 4×)

Profiler 结果颠覆了初步假设:

| 假设瓶颈 | 实测 |
|---|---|
| 主进程训练阻塞 | **错**。train_step backward 总计 0.08s / 4 局 |
| Queue pickle 开销 | **错**。主进程 67.5s / 68.6s 在 `posix.read`(等 worker) |
| Worker 互抢核 | **对**。4 worker 各跑 batch=1 推理,1600 次小 matmul 互相抢 CPU + 带宽 |

**根因:** 每个 worker 的 NN eval 都是 batch=1,M 系列 CPU 上 matmul
小批次效率极低,且 4 worker 同时抢同一批核心使情况恶化。

## 目标

1. **推理集中化 (B)**:跨 worker 合并 MCTS leaf eval 为动态 batch(目
   标 batch=32+),单次 matmul 的吞吐提升 5-10×
2. **异步流水 (C)**:selfplay 和 training 完全脱钩,worker 用比主进
   程落后 K 局的 weights 采样,去掉同步屏障
3. **可扩展至 8-16 worker**:MCTS 树逻辑本身 CPU 占用极轻,worker
   不再受 NN 推理抢核影响,可以开更多
4. **不牺牲收敛正确性**:stale weights 是标准 AZ 工程实践(Lc0 /
   ELF OpenGo 都这么做),终局 z 仍然是 on-policy 信号
5. **arena / gauntlet 不变**:评估路径仍走 main 的本地 agent,不经
   server

## 进程拓扑

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

三类进程:

1. **Main (coordinator + trainer)**
   - 持 ReplayBuffer(唯一一份)
   - train loop 独立消费 buffer(自己的节拍,不等 worker)
   - drain worker 返回的 trajectory,放 buffer
   - 周期性 push 最新 CPU state_dict 给 inference server
   - arena / gauntlet 在 main 跑(用 main 的本地 agent)

2. **Inference server(单一进程)**
   - 持一份 network weights(可能比 main 落后 K train steps)
   - 动态 batch:从 worker 请求中收集 ≤ `max_batch` 个或等 `batch_timeout_ms`,整批一次 forward,分发结果
   - 周期性从 main 拉 new weights,空闲时 load
   - cache hook_emb:keyed by `(worker_id, game_id)`,worker 在
     game 开始时上传 game_static,结束时释放

3. **Worker × N**(不持 network)
   - 只跑 MCTS 树逻辑 + env step + 确定化采样
   - 每次 `_eval_leaf` 通过 RPC 调 server
   - Trajectory 完成后推给 main 的 result_queue

## 消息协议

### Worker → Server(eval RPC)

**GameStart**(每局开始一次):
```python
{"kind": "game_start",
 "worker_id": int, "game_id": int,
 "game_static": dict}          # hooks, counters, cards
```
Server 编码 hook_emb + card_emb,缓存,回 ACK。

**Eval**(每次 rollout leaf):
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

**GameEnd**(每局结束一次):
```python
{"kind": "game_end", "worker_id": int, "game_id": int}
```
Server 从缓存中剔除对应条目。

### Main → Server(weight sync)

```python
{"kind": "weight_update", "weights": cpu_state_dict, "version": int}
```
Server 在两次 batch 之间的空闲点应用。version 用于日志 / 调试。

### Worker → Main(trajectory)

和当前 `parallel_selfplay.py` 的 result_queue 一致,结构不变,
`ParallelSelfPlayPool` 里的 `_ResultShim` 路径可以直接复用。

## 推理 server 细节

### 动态 batching

```python
def run_batch(deadline_ms):
    batch = []
    deadline = now() + deadline_ms
    while len(batch) < max_batch_size:
        timeout = max(0, deadline - now())
        try:
            req = in_queue.get(timeout=timeout/1000)
            batch.append(req)
        except Empty:
            break
    if batch:
        forward(batch)
```

参数初值(可调):
- `max_batch_size = 32`(worker=4 时 ≈ 8 per worker)
- `batch_timeout_ms = 3`(延迟 vs batch 充实度权衡)

理由:worker 同时在 rollout 时,大部分时间有 eval 在飞,timeout 不
会频繁触发;当 worker 少或卡在 env step 时,timeout 保底快速返回。

### hook_emb 缓存

当前 `Agent.eval_state` 里 `static_obs_hash` 做了同一局内的复用。
server 化后,缓存语义不变但持有者变:

- Key: `(worker_id, game_id)`
- Value: `(hook_emb, card_emb)` tensor
- 容量:`n_workers`(每 worker 最多一局同时在跑)
- 淘汰:GameEnd 显式剔除;worker 进程崩溃时由 heartbeat 超时清理
  (v1 不做,fail-fast)

### 权重更新

Main 节奏(独立于 worker):
- 每 `train_step_per_push` 次 train 完成后 push 一次(初值 10)
- 不等 server ACK,直接继续训练

Server 节奏:
- `weight_update` 放在**独立 queue**,不和 eval request 混
- 每次 batch 结束后检查 weight queue;有 update 就 `load_state_dict`
- 典型 stale 上界:`(train_step_per_push × train_steps_per_game) ×
  (game 平均时长)`。按初值估计 ≈ 10-30 局

### Arena / Gauntlet

**不走 server**。Main 持有本地 `Agent`(一直是最新 weights),arena
match 和 gauntlet 评估直接用 local agent.eval_state。理由:

- arena/gauntlet 频率低(每 100 局一次),吞吐不敏感
- 评估必须用**确定版本**的 weights,走 server 会拿到随机时刻的
  stale 版本,污染比较
- 避免 server 被评估流量打乱正常 selfplay batch 节奏

## Worker 改造点

### MCTS kernel

仅一处改动:`training/az/mcts/rollout.py::_eval_leaf`

```python
# 之前:
prior, v = agent.eval_state(static, dyn, refs, payments)

# 之后:
prior, v = inference_client.eval(static_key, dyn, refs, payments)
```

`inference_client` 是 worker 进程内的轻量 RPC client,持 Pipe /
Queue 句柄到 server,`eval` 同步阻塞等返回。MCTS 循环的其他部分
(select / expand / backprop)完全不动。

### Game lifecycle

Worker 开局时:
```python
client.game_start(game_id, game_static)  # server 缓存 hook_emb
for move in game:
    mcts_search(...)   # 内部触发 N 次 client.eval
    env.step(...)
client.game_end(game_id)
result_queue.put(trajectory)
```

## Main 改造点:异步流水

当前 `_parallel_selfplay_loop` 是"收一场 → 训一次 → dispatch 下一
场"的同步循环。改成两个独立线程:

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

**Dispatch**(一次性初始化):
开局时直接派 `n_games` 个 play 命令给 worker pool;worker 完一局
自己结束,不需要 main 再喂。

**Arena / Gauntlet**(train thread 内调度):
```python
if games_completed % games_per_arena == 0 and games_completed > last_arena_at:
    run_arena(local_agent, ...)
    last_arena_at = games_completed
```

注意 arena 触发用 ingest thread 更新的 `games_completed`,train
thread 读。简单 `threading.Event` / 原子 int 即可。

## 正确性 / 开放问题

### Q1:stale weights 上界

按上述参数粗估 stale = 10-30 局。worker 采样到旧 policy / value
估计,但 z 和 MCTS 访问分布本身**不依赖 weights 版本**(来自实际
对局结果),训练目标没有偏差。

Lc0 / ELF 的经验:stale 100+ 局也收敛。C1 规模下用 30 局上界很
安全。**无需额外文档标注"算法近似"。**

### Q2:死锁风险

- Worker 发 eval 请求 → server 暂停等 batch 凑齐 → 同时 main 在
  push weights → server 卡在 load_state_dict → worker 超时
- 解法:weight update 只在 batch forward **结束后**应用,不打断正
  在飞的 batch

### Q3:失败恢复

- Worker 崩溃:server 持有的 cache 条目永远悬挂(v1 忽略,C1 规模
  worker 不会崩太多)
- Server 崩溃:worker 全部卡住 → main 检测 heartbeat 超时 → fail-
  fast 整个 run
- **v1:任何异常均整体 raise + 停机,不做部分恢复**

### Q4:RPC transport 选型

选项:
- **A** `mp.Queue`(pickle 每次):简单,每次 RPC pickle/unpickle
  开销约 50-100µs,可接受
- **B** Per-worker `mp.Pipe`:更快,双向,server 用 `multiprocessing.
  connection.wait` 轮询所有 pipe
- **C** Shared memory ring buffer + semaphore:最快,复杂度高

**v1 选 B**(pipe)。pickle 开销比 A 小,比 C 实现简单。server 用
`connection.wait(pipes, timeout)` 收集请求天然契合动态 batching。

测出 pipe pickle 占比 >15% 再考虑升级到 C。

### Q5:GPU

server 是单进程,可以直接把 network 搬到 MPS / CUDA。worker 完全
不变(RPC 层不关心 server 在哪算)。

**实测结论**:d_model=64 下 MPS 3-4× 慢于 CPU(见"实测性能"一节
MPS GPU 失败数据)。C1 规模不使用 GPU。未来 d_model≥256 或
batch≥64 时重新评估。

## 增量实现顺序

按可独立测试的边界拆:

1. **InferenceServer 最小骨架**:单 worker,同步 batch=1,跑通
   game_start / eval / game_end / stop 协议。对比本地 agent.eval_state
   结果数值一致
2. **Dynamic batching**:加 max_batch + timeout,并发 2-4 worker
   测吞吐
3. **Weight sync**:加 weight_update 协议,独立 queue,数值测试
   (push 后下一次 eval 结果应该变)
4. **Worker 改造**:MCTS kernel 换 `inference_client.eval`,端到端
   4 worker smoke
5. **Async main**:ingest / train 拆线程,arena/gauntlet 走本地
   agent
6. **基准测试**:c1-scale, n_workers ∈ {1, 4, 8} × 开/关 async
7. **替换 `parallel_selfplay.py`**:老实现保留到新的通过 10 局
   c1-scale 测试后再删
8. **文档更新**:`../training/az_loop.md` 加本架构小节,
   `implementation.md` 勾上

## 实测性能

### 虚损失并行 rollout

基准条件:`d_model=64`,`n_cross_layers=2`,`n_rollouts=400`,MacBook
M 系列 CPU,`n_games=4`:

| 配置 | 同步 par=1 | 虚损失 par=4 | 加速 |
|---|---|---|---|
| nw=1 | 41.4s/game | 21.3s/game | 1.94× |
| nw=4 | 17.5s/game | **11.8s/game** | 1.49× |

par=8 实测和 par=4 持平,说明 server 已经饱和 — 进一步加
parallel_rollouts 不会继续给收益。

### batch_mean=4 的来源

虚损失流水线的加速（单 worker 1.94×）来自**重叠**,不是 batch 摊薄：
worker 内并行发出 4 条 rollout 的 eval 请求,在等待某条返回期间其他
rollout 可以继续 select/expand,从而把等待时间与树操作重叠。

但 server 端的实际 batch 大小受限于 n_workers,因为每个 worker 是
同步的（send-1-recv-1 稳态）。4 worker × par=4 并不会产生 batch=16
的请求堆积——每个 worker 在任意时刻最多有 1 个 eval 请求在飞（发出
后立即阻塞等回复）,所以 server 最多凑到 batch=n_workers=4。

真正的加速来自流水线重叠,不是 batch 摊薄。

### MPS GPU 失败

d_model=64 在 MPS 上 3-4× **慢于** CPU:

| 配置 | CPU | MPS | 倍率 |
|---|---|---|---|
| nw=1 | 38.0s | 148.6s | 3.91× 慢 |
| nw=4 | 17.2s | 64.0s | 3.72× 慢 |

根因：kernel launch overhead 在小矩阵乘法上主导耗时。d_model=64
的 matmul 计算量极小,MPS 每次 kernel dispatch 的固定开销远超实际
计算时间。需要 d_model≥256 或 batch≥64 才可能让 MPS 有正收益。
C1 规模暂不使用 GPU。

### C1 验证 run 耗时估算

2000 局, 4 worker, par=4:
- 老并行:~9.5 小时
- B+C sync:~9.5 小时
- B+C + virtual loss:**~6.6 小时**

打破这个天花板需要多 inference server 进程、或 GPU server、或减少
每次 eval 的 Python/torch 开销(#155 Go 化 rollout 路径)。

## 非目标

- ❌ 完全对等的分布式训练(single machine only)
- ❌ 跨机 RPC(localhost pipe only)
- ❌ Trajectory 的 zero-copy 传输(先用 pickle,测过再优化)
- ❌ Worker 热添加 / 动态扩缩(固定 n_workers 启动时定)
- ❌ 推理 server 的 failover(崩了就整体重启 run)
