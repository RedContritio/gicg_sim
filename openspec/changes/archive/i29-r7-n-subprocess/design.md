# I29 R7 — N independent Go subprocesses (mimic Python mp 进程模型)

**Date**: 2026-05-25 session 4
**Parent**: I29 (`feature/i29-redesign` branch)
**Predecessor**: post-C1+C2+I2 (commit `2b44d8d`) — fair-budget bench Go/Py = 0.68x
**Status**: Proposed (本 spec 即 implement contract)

## Goal

Mac M4 N=4 fair-budget bench **Go fps/actor ≥ Python mp fps/actor**。 同 cfg / 同硬件 / 同 seed,Go subprocess pipeline 在 mixed-opp workload 下不慢于 Python mp pipeline。

## First-principle motivation

User 2026-05-25 session 4 强约束:
> 哪怕完全保持 python 代码结构不变,直接改写成 go,也不应该性能更差。

R1 audit findings (Python mp arch):
- **N+2 truly independent OS process** (spawn ctx, 1 master + N actor + 1 InfServer)
- **Actor → InfServer 直 mp.Queue**(POSIX pipe + pickle, ~50-200µs/call,无 bridge)
- **Master → actor 无 task queue**(actor 自 sample spec)
- **InfServer 内单一 `_server_loop` thread** drain mp.Queue + batch forward + scatter resp
- 关键:**zero bridge layer between actor and InfServer in Python mp path**

当前 Go subprocess architecture (post-C1+C2+I2):
- 1 Go subprocess containing **N goroutine** (vs Python N independent process — forfeit OS-level parallelism)
- Inference 走 SHMRing + **InferenceShmBridge thread** in InfServer subprocess (vs Python mp 无 bridge — extra layer hop per call)

Bench data shows 0.68x ratio。 First-principle 路径:消除这两个 structural 差异,Go ≥ Python by construction (相同 IPC wire + Go internal 计算 ≥ Python)。

## Design

### Architecture

```
┌───────────────────────────┐
│ Master Python             │
│ - driver train loop       │
│ - SHMRing.try_pop trans   │ ← MPSC,N producer,1 consumer
└───────────────────────────┘
            ↑
            │ SHMRing trans (shared, cross-lang via gicg_actor/shm)
            │
┌──────────────────────┐  × N (independent OS subprocess, mimic Python mp)
│ Go actor[i] subproc  │  (cmd/gicg_actor with NActors=1)
│ - 1 paradigm.Run goroutine
│ - 1 TCP InferenceClient
└──────────────────────┘
            ↓
            │ TCP socket inference per-actor
            ↓
┌────────────────────────────┐
│ InferenceServer mp.Process │
│ - socket_listener thread   │ ← N TCP clients (1 per Go actor subprocess)
│ - _server_loop main thread │ drain request_q → batch forward → response_qs[cid]
└────────────────────────────┘
```

Process count: **N + 2** (1 master + N Go actor subprocess + 1 InfServer mp.Process)— 完全 mirror Python mp 的 N+2 topology。

### Key invariants

1. **N independent OS subprocess for actors** (vs current 1 subprocess containing N goroutine)。 OS scheduler + process isolation与 Python mp 等价
2. **NO bridge thread between Go actor and InfServer** (删 InferenceShmBridge + SHM inference path 全套)。 InfServer 端 `socket_listener` thread (R-RR.4 ship,已存在) 接 TCP request → `request_q.put` → 同 mp 路径 batch forward,与 Python mp `actor_client.request_queue.put` 同 wire pattern
3. **Shared SHMRing trans** (MPSC, current cross-lang impl `gicg_actor/shm/` works)。 N Go subprocess 各 attach by name + push,master 单 consumer。 与 Python mp `SHMRing` 等价 wire
4. **No regression to deleted 概念**: cgo path (P3 deleted), N goroutine in 1 subprocess (R7 deleted)
5. **inference_mode='tcp' only** — 删 'shm' inference path 全套 (InferenceShmBridge + InferenceShmClient + SHMReqRingName/SHMRespRingNames cfg fields + parseConfig SHM 分支 + buildShmInferenceClients)

### Components changed

**Modified**:
- `training/core/actor/go_subprocess_pipeline.py`: `spawn_pipeline` 改 spawn N Go subprocess (一个 per actor) 而非 1 subprocess NActors=N。 `PipelineHandle` 包含 N `GoSubprocessHandle`。 `shutdown` atomic teardown N subprocess + 1 SHM ring + 1 InfServer
- `training/paradigms/dmc/go_subprocess_collector.py`: 接 N-subprocess `PipelineHandle`,collect / sync_weights / close 流程透传 N
- `training/core/config/base.py`: `PipelineCfg.inference_mode` 删 (回 'tcp' only,不需 cfg 字段)
- `training/paradigms/dmc/paradigm.py`: `_make_go_collector` 删 inference_mode 透传
- `cmd/gicg_actor/main.go`: 删 SHM inference path (`InferenceShmMode` + `SHMReqRingName` etc Config fields + `buildShmInferenceClients`)
- `gicg_actor/pool.go`: Config 删 SHM inference 字段。 NActors=1 仍 valid (paradigm.Run for loop 跑 1 iter)
- `gicg_actor/inference_client.go`: TCP InferenceClient 保留 (only inference impl)
- `training/core/actor/inference_server.py`: 删 `shm_inference_cfg` 参数 + 相关 branch。 socket_listener thread 保留

**Deleted**:
- `gicg_actor/inference_shm_client.go` + `gicg_actor/inference_shm_client_test.go`
- `training/core/actor/inference_server_shm_bridge.py`
- `configs/dmc/bench_v_legacy_go.toml` 内 `[pipeline] inference_mode = "shm"` 字段 (cfg 默认 OK,直接删整 [pipeline] section)
- 相关 SHM inference 测试 (if any survived P3)

### LOC budget

- Deletions: ~600 LOC (InferenceShmClient + bridge + SHM inference cfg fields + tests)
- Modifications: ~250 LOC (pipeline.py N-fanout, collector.py wrapping, cfg cleanup)
- **Net delta**: ~-350 LOC (持续 simplify trend)

## Implementation phases (subagent-driven)

**R7.1 — 删 SHM inference path** (subagent task,~200 LOC delete):
- 删 `gicg_actor/inference_shm_client.go` + test
- 删 `training/core/actor/inference_server_shm_bridge.py`
- `gicg_actor/pool.go`: Config 删 SHM inference 字段 (`InferenceShmMode` / `SHMReqRingName` / `SHMRespRingNames` / `SHMReqCapacity` / `SHMReqSlotSize` / `SHMRespSlotSize`)
- `cmd/gicg_actor/main.go`: 删 `InferenceShmMode` + 相关 fields + `buildShmInferenceClients` + parseConfig SHM 分支
- `training/core/actor/inference_server.py`: 删 `shm_inference_cfg` 参数 + 相关 branch
- `training/core/actor/go_subprocess_pipeline.py`: 删 `inference_mode='shm'` 分支
- `training/paradigms/dmc/go_subprocess_collector.py`: 删 `inference_mode` ctor 字段 + 相关 ctor param
- `training/core/config/base.py`: `PipelineCfg.inference_mode` field 删
- `training/paradigms/dmc/paradigm.py`: `_make_go_collector` 删 inference_mode 透传
- cfg 文件: `configs/dmc/bench_v_legacy_go.toml` 删 `inference_mode = "shm"` line
- Verify: go build + go test PASS + Python smoke 5/5 PASS + DMC subprocess e2e 5/5 PASS (with TCP inference path)

**R7.2 — N-subprocess spawn 改造** (subagent task,~250 LOC modify):
- `training/core/actor/go_subprocess_pipeline.py`:
  - `spawn_pipeline` 改返 N `GoSubprocessHandle` list
  - 创 1 shared SHMRing trans channel (master owner)
  - spawn N Go subprocess (cmd/gicg_actor with NActors=1,各 attach 同 ring name + 自己 TCP inference port)
  - wait N READY signal
  - `PipelineHandle` 包 list[handle] + shared SHM ring + InfServer
  - `shutdown` 全 N subprocess SIGTERM in parallel + join
- `training/paradigms/dmc/go_subprocess_collector.py`:
  - 接 N-handle PipelineHandle
  - collect 流程不变 (master 仍 single SHMRing poll)
  - close 透传 N teardown
- Verify: pytest test_go_subprocess_5ep_e2e PASS (本 test 现 spawn N=2,改造后应仍 5ep 全 assemble + clean shutdown)

**R7.3 — Mac fair bench verify** (我 直接跑,not subagent):
- `tools._bench.run_mac_collector_pair --n-actors 4 --seeds 3`
- 期望 Go fps/actor ≥ Python mp fps/actor (gate met)
- 若 ratio < 1.0,profile + 决策 fix path (留 R7.4 emergent)

## Out of scope

- Win box gate (Mac-only acceptance per session 3 reviewer audit)
- 其他 paradigm port (AZ/PPO/CFR/BC) — DMC ship 后另立
- InfServer GPU pipeline / batching window 优化 — 不在 R7 范围
- Linux GPU box verify — Mac M4 ship gate

## Risk

1. **N subprocess startup cost vs 1 subprocess** — Go binary cold-start ~ms × N。 spawn 走 parallel `subprocess.Popen` + 各 wait READY,total wall ~max(per-startup) 不是 sum。 N=4 应 < 5s acceptable
2. **TCP localhost inference latency vs SHMRing** — TCP ~10-30µs/call,SHMRing ~5µs (但加 bridge layer 30-100µs 总)。 实测 TCP 应 ≥ SHM path (无 bridge layer)
3. **SHMRing trans contention with N producer** — current impl 用 CAS-safe MPSC,N=4 应不撞 lock contention (push 频率 ~episode/几秒级,远低于 contention threshold)

## Acceptance gate

R7.3 Mac N=4 × ≥3 seed fair-budget bench 显示 **Go fps/actor mean ≥ Python mp fps/actor mean** (point estimate, allowing std overlap 因 Mac variance)。 若 ratio ∈ [0.9, 1.1] (stat tie), 接受 ACCEPT。 若仍 < 0.9, R7.4 deeper profile + 决策。
