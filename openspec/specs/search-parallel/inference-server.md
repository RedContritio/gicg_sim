---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: search-parallel
subtopic: inference-server
---

# Inference Server — 动态 batching / hook_emb 缓存 / 权重更新 / arena 旁路

> 本 subtopic 锚定 GICG inference server 进程的内部规约 — 动态
> batching 算法、hook_emb 缓存语义、权重更新调度、Arena/Gauntlet 不走
> server 决策、失败恢复。进程拓扑见 [`./topology.md`](./topology.md);
> 消息协议见 [`./protocols.md`](./protocols.md)。

## 1. 动态 batching

### 1.1 SHALL invariants

1. Server SHALL collect eval requests up to `max_batch_size` OR until
   `batch_timeout_ms` deadline,whichever first。
2. Default cfg-driven 初值:`max_batch_size = 32`、`batch_timeout_ms = 3`。
3. SHALL forward the collected batch as a single network call(单次
   matmul 摊薄 kernel launch / activation 内存 overhead)。
4. Empty batch SHALL be skipped(timeout 命中但无 request 时,继续
   下一轮收集,不做空 forward)。

### 1.2 算法伪代码

```python
def run_batch(deadline_ms):
    batch = []
    deadline = now() + deadline_ms
    while len(batch) < max_batch_size:
        timeout = max(0, deadline - now())
        try:
            req = in_queue.get(timeout=timeout / 1000)
            batch.append(req)
        except Empty:
            break
    if batch:
        forward(batch)
```

### 1.3 参数权衡

- `max_batch_size = 32`:worker=4 时约 ≈ 8 req/worker 在飞(virtual-loss
  par=4 单 worker 1 req 在飞稳态)。
- `batch_timeout_ms = 3`:延迟 vs batch 充实度权衡。Worker 同时在
  rollout 时大部分时间有 eval 在飞,timeout 不会频繁触发;worker 少
  或卡在 env step 时,timeout 保底快速返回。
- 关于"虚损失 par=4 不会产生 batch=16 而是 batch ≤ n_workers"的实测
  分析见 [`docs/5_history/search_history.md`](../../../docs/5_history/search_history.md) §"batch_mean=4 的来源"。

## 2. hook_emb 缓存

当前 `Agent.eval_state` 里 `static_obs_hash` 做了同一局内的复用。server
化后,缓存语义不变但持有者变。

### 2.1 SHALL invariants

1. Cache key SHALL be `(worker_id, game_id)`。
2. Cache value SHALL be `(hook_emb, card_emb)` tensors(per-game 不变,
   静态 obs 编码结果)。
3. Cache 容量 SHALL be at least `n_workers`(每 worker 最多一局同时
   在跑)。
4. Cache eviction SHALL be triggered by `GameEnd` message — 显式剔除,
   SHALL NOT 隐式 LRU。
5. Worker 崩溃 → cache 条目悬挂:v1 SHALL NOT 做 heartbeat 超时清理
   (fail-fast 整体 raise + 停机,详 [`./topology.md`](./topology.md) §6.2)。
6. 缓存查询 miss(`eval` 携带的 `(worker_id, game_id)` 不在 cache)
   SHALL raise — 表明 protocol 顺序错误(未 `game_start` 就 `eval`),
   非合法状态。

### 2.2 缓存生命周期

```
worker.game_start(game_id, game_static)
  → server.encode hook_emb + card_emb
  → server.cache[(worker_id, game_id)] = (hook_emb, card_emb)
  → ACK

worker.eval(game_id, dyn, refs, payments) × N
  → server.cache[(worker_id, game_id)] 取 (hook_emb, card_emb)
  → cross-attn + heads forward
  → reply (prior, value)

worker.game_end(game_id)
  → server.cache.pop((worker_id, game_id))
```

## 3. 权重更新调度

### 3.1 Main push 节奏

1. Main SHALL push weights every `train_step_per_push` train steps
   (初值 10)。
2. Main SHALL NOT wait for ACK after push — fire-and-forget,继续
   train loop。

### 3.2 Server apply 节奏

1. Server SHALL place `weight_update` messages in an **independent
   queue**(不与 eval request queue 混)— 防互相阻塞。
2. Server SHALL check weight queue **after each batch forward
   completes** — SHALL NOT preempt in-flight batch。
3. When weight update is pending,server SHALL `load_state_dict`
   between batches — 全部加载完成后才接下一个 batch。
4. Latest version SHALL replace earlier pending versions(若 main 连续
   push 2 次而 server 还没 apply 第一次,只 apply 最新的;`version`
   字段用于日志/调试 only)。

### 3.3 Stale weights 上界

1. 典型 stale 上界:`(train_step_per_push × train_steps_per_game) ×
   (game 平均时长)`。按初值估计 ≈ 10-30 局。
2. Stale 是标准 AZ 工程实践(Lc0 / ELF OpenGo stale 100+ 局也收敛):
   - worker 采样到旧 policy / value 估计
   - **但** z 与 MCTS 访问分布**不依赖 weights 版本**(来自实际对局结果)
   - 训练目标(`z` for value head,`visits/sum(visits)` for policy
     head)没有偏差
3. 因此 stale weights SHALL NOT be labeled as "算法近似" — 与其他
   工程优化(c-shared library / Go MCTS migration)同级。

### 3.4 死锁防护

1. Weight update 只在 batch forward **结束后**应用,不打断正在飞的
   batch — 保证 worker eval 不会因 server 卡在 `load_state_dict` 而
   超时。
2. 若未来加入 server failover,SHALL go through OpenSpec change(当前
   非目标,见 [`./spec.md`](./spec.md) §6)。

## 4. Arena / Gauntlet bypass server

### 4.1 SHALL invariants

1. Arena match 与 Gauntlet evaluation SHALL use **trainer main's local
   agent**(始终最新 weights),SHALL NOT route through inference server。
2. 评估调用入口 SHALL be `local_agent.eval_state(...)`(直接 forward,
   不经 RPC)。

### 4.2 决策理由

1. **评估必须用确定版本 weights** — 走 server 会拿到随机时刻的 stale
   版本,污染比较(无法判断 model_A vs model_B 哪个更强,因为两者用
   了不同的 stale 程度)。
2. **arena/gauntlet 频率低** — 每 100 局一次,吞吐不敏感,直接 local
   forward 即可。
3. **避免 server 被评估流量打乱正常 selfplay batch 节奏** — server
   batch 应稳定在 self-play workers,arena 临时打入会扰动 batch
   composition。

## 5. 增量实现顺序

按可独立测试边界 SHALL implement:

1. **InferenceServer 最小骨架**:单 worker,同步 batch=1,跑通
   game_start / eval / game_end / stop 协议。对比本地 `agent.eval_state`
   结果数值一致
2. **Dynamic batching**:加 `max_batch` + `timeout`,并发 2-4 worker
   测吞吐
3. **Weight sync**:加 weight_update 协议,独立 queue,数值测试
   (push 后下一次 eval 结果应该变)
4. **Cache lifecycle test**:`game_start` → N × `eval` → `game_end`,
   缺步骤应 raise

(完整 8 步增量见 [`./topology.md`](./topology.md) §5)

## 6. 开放问题

### 6.1 死锁场景诊断

- Worker 发 eval → server 等 batch 凑齐 → main push weights → server
  卡 `load_state_dict` → worker 超时
- **解法**:Weight update 只在 batch forward **结束后**应用(本
  subtopic §3.4)

### 6.2 GPU 决策

1. Server 是单进程,可直接搬 network 到 MPS / CUDA。Worker 完全不变
   (RPC 层不关心 server 在哪算)。
2. **历史结论**:d_model=64 下 MPS 3-4× 慢于 CPU(详
   [`docs/5_history/search_history.md`](../../../docs/5_history/search_history.md))。
   C1 规模不使用 GPU。
3. 未来 `d_model ≥ 256` 或 `batch ≥ 64` 时重新评估;SHALL go through
   OpenSpec change(配置新 inference server 类型)。

## 7. Cross-references

- [`./topology.md`](./topology.md) — 三进程类型职责
- [`./protocols.md`](./protocols.md) — 三 channel IPC 消息字段定义
- [`../search-ismcts/algorithm.md`](../search-ismcts/algorithm.md) §3.1
  — leaf eval 由本 server 提供 `prior` + `value`
- [`../network-architecture/encoders.md`](../network-architecture/encoders.md) —
  hook_emb / card_emb encoder 结构(本 server cache 的内容)
- [`../network-architecture/heads.md`](../network-architecture/heads.md) —
  value head 输出 `[-1, 1]` + policy head pointer-net(本 server 返回
  字段语义)
