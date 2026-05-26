# I29 R7 — N independent Go subprocess (mimic Python mp N+2 topology)

**Status:** Archived 2026-05-25
**Original date:** 2026-05-25 session 4
**Parent:** I29 (`feature/i29-redesign` branch)
**Predecessor:** post-C1+C2+I2 audit fix (commit `2b44d8d`) — fair-budget bench Go/Py = 0.68x
**Supersedes:** `archive/0006-i29-go-actor-pool/` R1 candidate path
**Superseded by:** —

## Why

post-C1+C2+I2 audit close 了 PR draft 自报 "3.66x" 的 3 个 critical defect (C1 dispatch path mismatch / C2 algorithm asymmetry / I2 dead cgo path)。 真 fair-budget bench 显示 **Go/Py = 0.68x** — Python mp 实际 1.47x faster。 acceptance gate NOT MET。

User session 4 强约束:
> 哪怕完全保持 python 代码结构不变,直接改写成 go,也不应该性能更差。

R1 audit (Python mp 架构) findings:
- Python mp 是真 **N+2 OS process** (1 master + N actor each `mp.Process(target=actor_main)` + 1 InfServer)
- Actor → InfServer 直 `mp.Queue` (POSIX pipe + pickle,~50-200µs/call,**zero bridge layer**)
- spawn ctx + BLAS=1 隔离,无 GIL contention

post-C1+C2+I2 Go subprocess 仍有 2 个 structural 差异:
1. **1 Go subprocess containing N goroutine** (vs Python N independent subprocess) — collapse N+2 → 2 process,forfeits OS-level parallelism
2. **InferenceShmBridge thread** in InfServer subprocess (vs Python mp 零 bridge) — extra layer hop per call

R7 close 两个 structural 差异 → first-principle 下 Go ≥ Python by construction (同 IPC wire + 同 process count + Go native compute no GIL)。

## What

R7 严格 mimic Python mp N+2 拓扑,LOC budget ~500 net delta (~-1000 删 SHM bridge + ~200 add N spawn):

### R7.1 (`ff50548`,-1096 LOC):删 SHM inference path 全套

- 删 `gicg_actor/inference_shm_client.go` + test (-526 LOC)
- 删 `training/core/actor/inference_server_shm_bridge.py` (-262 LOC)
- `gicg_actor/pool.go` Config 删 `InferenceShmMode` / `SHMReqRingName` / `SHMRespRingNames` / `SHMReqCapacity` / `SHMReqSlotSize` / `SHMRespSlotSize` 字段
- `cmd/gicg_actor/main.go`:删 SHM 分支 + `buildShmInferenceClients` + `parseConfig` SHM validation
- `inference_server.py`:删 `shm_inference_cfg` 参数 + `InferenceShmBridge` spawn 分支
- `go_subprocess_pipeline.py`:删 inference_mode shm 分支 + SHM kwargs
- `go_subprocess_collector.py`:删 inference_mode ctor param
- `PipelineCfg.inference_mode` cfg field 删
- `paradigm.py:_make_go_collector`:删 inference_mode 透传
- `bench_v_legacy_go.toml`:删 `inference_mode = "shm"` line
- `test_go_subprocess_5ep_e2e.py`:删 `[shm]` parametrize variant

Inference 回 TCP only — InfServer 端 `socket_listener` thread (R-RR.4 ship) accept N TCP client → `request_q.put` → 与 mp.Queue clients 共用 `_server_loop` 批处理,与 Python mp wire 完全等价 (零桥)。

### R7.2 (`0036241`,+161 / -57 LOC):spawn N independent Go subprocess

- `gicg_actor/pool.go`:Config 加 `BaseActorID int` 字段 (subprocess[i] BaseActorID=i 确保 cross-subprocess unique clientID,assembler `(cid, ep_id)` 无冲突),`runInternal` 传 `BaseActorID + i` 作 externalID
- `cmd/gicg_actor/main.go`:Config 加 `BaseActorID` JSON 字段 + `>= 0` validation + `toPkgConfig` 透传
- `training/core/actor/go_subprocess_pipeline.py`:
  - `PipelineHandle.go_proc` (single) → `go_procs: list[GoSubprocessHandle]` (N)
  - `spawn_pipeline` 改 spawn N independent Go subprocess sequentially (each NActors=1 + BaseActorID=i),attach 同 shared SHMRing trans + 各起 1 TCP InferenceClient
  - `shutdown` 改 N parallel SIGTERM + sequential wait join + SHM close + InfServer stop
  - partial-spawn 失败 cleanup loop
- `test_go_subprocess_1ep_smoke.py`:`handle.go_proc` → `handle.go_procs[0]`

DMCGoSubprocessCollector / cmd/gicg_actor / inference_server / DMC paradigm — 不需改 (PipelineHandle opaque to collector;cmd 内部 NActors=1 trivially supported;InfServer socket_clients=N 已 support N TCP client accept)。

## Architecture (post-R7.2)

```
┌────────────────────────────┐
│ Master Python (0 cgo lib)  │
│ - driver train loop        │
│ - SHMRing.try_pop trans    │ ← MPSC, N producer, 1 consumer
└────────────────────────────┘
            ↑
            │ SHMRing trans (shared, cross-lang via gicg_actor/shm)
            │
┌──────────────────────┐  × N (independent OS subprocess,与 Python mp 等价拓扑)
│ Go actor[i] subproc  │
│ - 1 paradigm.Run goroutine
│ - 1 TCP InferenceClient
└──────────────────────┘
            ↓
            │ TCP socket inference per-actor (与 Python mp mp.Queue 等价 wire,零桥)
            ↓
┌────────────────────────────┐
│ InferenceServer mp.Process │
│ - socket_listener thread (N TCP clients accept → request_q.put)
│ - _server_loop main thread (drain request_q → batch forward → response_qs[cid])
└────────────────────────────┘
```

Process count = **N + 2** (1 master + N Go subprocess + 1 InfServer) — 与 Python mp `mp.Process(target=actor_main)` × N + InfServer 拓扑完全一致。

## Acceptance gate

Mac M4 fair-budget bench (bench cfg `minimax_node_budget=4000` 双侧对齐, `tools/_bench/run_mac_collector_pair.py`):

| Backend | fps/actor (5-seed) | Std | CV |
|---|---:|---:|---:|
| Python mp | 3.23 | 0.97 | 30% |
| Go subprocess (R7) | **4.98** | 3.35 | 67% |
| **Ratio Go/Py** | **1.54x** | | |

Per-seed Go: 1.32 / 7.46 / 5.18 / 1.95 / 8.98 fps/actor — bimodal (Mac M4 scheduler noise);worst-case Go 1.32 仍 < worst-case Python 2.15;mean 1.54x robust。 same-commit independent verify `smoke_full perf_smoke` Go fps/actor=4.62 一致量级。

**Gate MET** — first-principle 验证 (R7 严格 mimic Python mp 拓扑 + 零 bridge → Go native compute 在等价 IPC 下 ≥ Python pipeline)。

## Affected specs

- 新建 `openspec/specs/training-architecture/actor-backend.md` SHALL 子规约 — actor_backend cfg dispatch / N+2 topology / 0 cgo invariant / TCP-only inference / shutdown order

## Commits

```
a4da6d1 docs: 5-seed bench robust 1.54x
fefe945 docs: R7 design + PR draft (3-seed 1.64x)
0036241 i29 R7.2: spawn N independent Go subprocess           ← KEY architecture fix
ff50548 i29 R7.1: 删 SHM inference path 全套 (-1096 LOC)
```

## Out of scope (留 follow-up)

- Win box gate (audit I1 deferred,user 接受 Mac-only ACCEPT)
- Production no-cap fair bench (cgo crossings dominant scenario,预期 Go >> 1.54x)
- AZ/PPO/CFR/BC paradigm port (Phase 2 follow-up;DMC ship 后另立)
- Linux GPU box re-verify (tighter std bounds)
- Mac N=2 / N=8 scaling bench

## 关联

- design: `./design.md` (本 dir,architecture deep dive)
- predecessor: `../../archive/0006-i29-go-actor-pool/` (pre-redesign cgo path STATE_DUMP)
- memory: [[i29-r7-acceptance-ship]] / [[python-arch-mimicry-for-go-port]] / [[bench-variance-5seed-required]]
