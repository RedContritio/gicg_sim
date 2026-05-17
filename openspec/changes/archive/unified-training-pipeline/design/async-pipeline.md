---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../design.md
---

# Async Pipeline — 5 角色 + SHM ring + 进程生命周期

> 治理 `training-architecture/spec.md` SHALL #4(placement)+ #7(pipeline
> mode dispatch)+ #9(weights sync 协议)落地。本文件聚焦 async mode
> 进程拓扑细节。

## 1. 5 角色拓扑

```
                            Replay Buffer SHM ring
  ┌─────────────┐         ┌──────────────────┐       ┌─────────────┐
  │ Actor × N   │────────▶│ N writers / 1 r  │──────▶│ Learner × 1 │
  │             │         └──────────────────┘       │             │
  │ Runner+Policy+Provider                            └──────┬──────┘
  └─────────────┘                                            │ atomic write
        ▲                                              ┌─────▼──────────┐
        │ provider.update_weights("latest")            │ Weights SHM    │
        └─── poll(slot_latest) ◀──────────────────────│ slot_latest +  │
                                                      │ slot_snapshot  │
  ┌────────────────┐                                  └─────┬──────────┘
  │ Inference     │ (optional, K servers, remote mode only)  │
  │ Server × K    │◀──── batched forward request from actors │
  └────────────────┘                                          │
                                                              ▼ snapshot
  ┌──────────────────┐                                     trigger
  │ EvalWorker × M   │   provider.update_weights("snapshot_eval_<id>")
  │                  │◀──────────────────────────────────────┘
  │ Runner+Policy+Provider
  └──────────┬───────┘
             ▼
        ┌──────────────────┐
        │ Eval results q   │──▶ EvalServer ──▶ metrics.jsonl + arena results
        └──────────────────┘
```

### 1.1 进程清单

| 角色 | 数量 | 默认 | Device 默认 | Placement 默认 |
|---|---|---|---|---|
| Actor | N | 24(cfg)| meta.device(CPU)| local |
| Learner | 1 | 1 | meta.device | n/a |
| Inference server | K | 0(local mode)/ 2(remote)| meta.device | n/a |
| EvalWorker | M | 4(cfg.eval.n_workers)| meta.device | local |
| EvalServer | 1 | 1 | n/a | n/a |

总进程数 = N + 1 + K + M + 1。GICG 默认 24 + 1 + 0 + 4 + 1 = 30 进程
(local mode)。Docker container 限制 9 CPU,所以 actor 数实际 8-16。

## 2. SHM ring buffer

`training/core/actor/shared_buffer.py`:

```python
class SHMRingBuffer:
    """N writer + 1 reader, lock-free.

    Slot table:
      - capacity: power of 2, default 2^16 = 65536 transition slots
      - element: pickle-serialized Transition, fixed max bytes
      - head: atomic int (writer claims next)
      - tail: atomic int (reader consumes)
    """
    def push(self, transitions: List[Transition]) -> None: ...
    def sample_recent(self, n: int) -> List[Transition]: ...
    def stale_count(self) -> int: ...
```

实现要点:
- POSIX shared memory + numpy frombuffer
- Head 通过 `numpy.atomic_compare_exchange` 或 `multiprocessing.Value('i')` lock
- Writer 满时 overwrite oldest(ring)
- Reader 每次取最近 K(static dedup,详 buffer/static_dedup.py)

## 3. Inference server(remote mode)

`training/core/actor/inference_server.py`:

```python
def inference_server_main(server_id: int, cfg: TrainingConfig,
                          weights_shm: WeightsSHM, request_socket: str):
    network = build_network(cfg).to(cfg.pipeline.inference.remote.device).eval()
    weights_watcher = WeightsWatcher(weights_shm, network, slot="latest")
    weights_watcher.start()

    server = UnixSocketServer(request_socket)
    pool_size = cfg.pipeline.inference.remote.max_batch
    timeout = cfg.pipeline.inference.remote.batch_timeout_ms / 1000

    while not should_stop():
        batch = server.collect_batch(max_size=pool_size, timeout=timeout)
        if not batch: continue
        obs_t, mask_t = stack_batch(batch)
        with torch.no_grad():
            out = network(obs_t, mask_t)
        for req, slice_ in zip(batch, unstack(out)):
            req.respond(slice_)
```

K = 2 时,actors 通过 hash(obs_pid) % K 路由,负载均衡。

## 4. EvalServer

`training/core/eval/server.py`:

```python
def eval_server_main(cfg: TrainingConfig, weights_shm: WeightsSHM,
                     job_queue: Queue, result_queue: Queue):
    scheduler = PeriodicScheduler(cfg.eval.schedule)  # every N step
    workers = spawn_eval_workers(M=cfg.eval.n_workers, ...)

    while not should_stop():
        if scheduler.due(current_step()):
            snapshot_id = snapshot_weights(weights_shm)   # cp latest → snapshot
            jobs = build_jobs(cfg.eval.scenarios, snapshot_id)
            for job in jobs: job_queue.put(job)
            results = drain_results(result_queue, expected=len(jobs))
            metrics = aggregate(results)                  # WP / CI95 / Wilson
            log_to_metrics_jsonl(metrics, current_step())
```

## 5. 进程生命周期 + 健康检查

每个 child process SHALL:
1. 启动时注册 PID 到 `runtime.processes_registry`
2. 每 30s heartbeat 写 `runtime/heartbeat/<role>_<id>`
3. SIGTERM 优雅停止:`stop_event.set()` + `transition_queue.close()`
4. Crash 时父进程 detect missing heartbeat → restart 同名进程(可选,默认
   raise + 整 run 失败)

详 `training/core/actor/runtime.py`。

## 6. Determinism in async

完全 deterministic 在 async mode **不可能**(actor 调度顺序非确定)。GICG
约定:
- 单 actor + serial mode:bit-exact reproducible
- N actor + async mode:**stat-reproducible**(seed → 同 distribution of
  trajectories,但具体顺序不固定)
- Eval mode:每 EvalWorker 用 `derive_seed(master, "eval_worker", id)` →
  同 cfg 同 step → 同 eval scenarios trace(per worker)

`weights_version_lag` metric 监控 stale 程度;> 100 step 算 warning。

## 7. 进程进度日志

每 actor / inference / eval worker 写 `metrics.jsonl` 一行 per 10s,字段:
- `actor.{id}.episodes_done`
- `actor.{id}.weights_version`
- `inference.{id}.batch_size_p50 / p99`
- `eval_worker.{id}.games_done`

详 [`./tools-layout.md`](./tools-layout.md)。

## 8. Cross-references

- Network provider → [`./network-provider.md`](./network-provider.md)
- Episode runner → [`./episode-runner.md`](./episode-runner.md)
- Config schema(remote 字段)→ [`./config-layered.md`](./config-layered.md)
- 当前 framework inference 实现 → `training/framework/inference/` ( P3 抽出)
