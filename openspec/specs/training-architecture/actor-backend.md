---
last_updated: 2026-05-25
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: actor-backend
parent: ./spec.md
---

# Actor Backend — collector dispatch + cross-language process topology

> 本 subtopic 治理 `cfg.pipeline.actor_backend` 的 dispatch matrix + Go
> backend 必满足的 N+2 OS process topology + 0 cgo invariant + inference
> wire 约束 + 启动/关闭顺序。 后于 I29 R7 ship (2026-05-25),取代 pre-redesign
> cgo c-shared lib + 1-process-N-goroutine path (`archive/0006-i29-go-actor-pool/`)。
>
> 适用范围:任何 `mode='async'` 的 paradigm collector dispatch。 `mode='serial'`
> 走 in-process,与本 subtopic 无关。

## 1. Purpose

跨语言 actor pool 设计长期面临 architecture trade-off:
- Python mp:N independent OS subprocess + mp.Queue / mp.SHMRing IPC,proven 性能 baseline
- cgo c-shared lib (pre-I29):Go runtime loaded master process,N goroutine 内 cgo call — master GIL contention 让 0.68x slower than Python mp
- standalone Go subprocess + master bridge thread (post-I29 C1+C2+I2):仍 collapse N+2 → 2 process + bridge layer → 0.68x slower than Python mp
- **N independent Go subprocess (I29 R7,本 subtopic 规约)**:严格 mimic Python mp N+2 拓扑 + 零 bridge layer → Mac fair bench 1.54x faster ✅

第一性原理论证 (本 subtopic invariant 直接 backing):**保持原架构 (process model + IPC wire) + 语言内化 only**。 Go native compute (no GIL / no pickle) 在等价 IPC 下应 ≥ Python pipeline by construction。 偏离架构 (collapse process count / 加 bridge layer) = forfeit OS-level 并行红利 + 引入新 overhead = 不可能 ≥ baseline。

memory backing:
- [[python-arch-mimicry-for-go-port]] — cross-lang port 设计准则
- [[i29-r7-acceptance-ship]] — R7 ship + bench progression (3.66x→0.68x→1.54x)
- [[audit-reviews-reveal-perf-artifacts]] — fairness claims 必经 4-dim audit

## 2. Scope

**In scope**:
- `cfg.pipeline.actor_backend` enum + dispatch contract
- Go backend N+2 OS process topology (1 master + N actor subprocess + 1 InfServer)
- 0 cgo lib loaded in master process (deal-breaker invariant)
- Actor ↔ InfServer inference wire (TCP-only,与 Python mp `mp.Queue` 等价 batch path)
- Master ↔ actor transition wire (SHMRing trans, MPSC shared)
- Atomic spawn / shutdown 顺序契约
- BaseActorID semantic (cross-subprocess unique clientID)

**Out of scope**:
- Paradigm internal 算法 (DMC opp / AZ MCTS 等) — paradigm dossier
- Inference batch tuning / GPU pipeline — `openspec/specs/training-architecture/network-sharing.md` + paradigm
- Eval path — `./eval.md`
- Cross-platform shm impl (POSIX / Win) — code-level `gicg_actor/shm/`,不需 spec
- Production no-cap bench / Win box re-verify — follow-up tickets,不在 R7 acceptance gate 范围

## 3. SHALL invariants (AB1-AB12)

### 3.1 Dispatch matrix

**AB1**: `cfg.pipeline.actor_backend` SHALL ∈ `{'python', 'go'}`。 默认 `'python'`。 其他值 → cfg loader raise (`config-schema` strict)。

**AB2**: `mode='serial'` 时 `actor_backend` 字段 SHALL 被忽略 (serial 走 in-process)。 `mode='async'` 时 `actor_backend` 控制 collector class:
- `'python'` → paradigm 的 `make_collector` 返 Python mp collector (e.g. `DMCMultiProcessCollector`)
- `'go'` → paradigm 的 `make_collector` 返 Go subprocess collector (e.g. `DMCGoSubprocessCollector`)

**AB3**: paradigm 实现 `actor_backend='go'` 是 OPTIONAL。 paradigm 不 support `'go'` 时 SHALL raise `ValueError` 显式 (current state: DMC ✅,AZ/PPO/CFR/BC 不 support — `_make_<paradigm>_collector` raise)。

### 3.2 N+2 OS process topology (Go backend only)

**AB4**: `actor_backend='go'` SHALL spawn 总 **N + 2 independent OS process**:
- 1 master Python process (driver train loop + buffer)
- N Go actor subprocess (each `cmd/gicg_actor` standalone binary,`NActors=1` per subprocess,via `subprocess.Popen`)
- 1 InferenceServer Python subprocess (`mp.Process(target=_server_loop)`,torch / GPU forward)

**AB5**: Master Python process SHALL NOT load any cgo lib (`libgicg_actor` / `libgicg`)。 deal-breaker invariant — collapse N+2 → 2 process + GIL contention 是历史 0.68x slower 的 root cause。 verify gate:`test_go_subprocess_5ep_e2e.py` 内 `ps -o command` grep `libgicg_actor` empty。

**AB6**: 每 Go actor subprocess SHALL 是 independent OS process (各 PID 独立,各 Go runtime 独立)。 不允许 "1 Go subprocess containing N goroutine" (R7 pre-redesign architecture,已 retired)。

### 3.3 IPC wire (no bridge layer)

**AB7**: Actor ↔ InferenceServer SHALL 走 TCP socket per-actor。 InfServer 端单一 `socket_listener` thread accept N TCP client → `request_q.put` → 与 mp.Queue clients 共用 `_server_loop` batched forward。 **零 bridge thread** between accept 与 `request_q` (无 `InferenceShmBridge` 等中介 layer)。

**AB8**: Master ↔ actor SHALL 走 SHMRing trans (cross-lang POSIX shm via `gicg_actor/shm/`)。 N producer Go subprocess attach 同一 ring name (MPSC),master 单 consumer 周期 `try_pop_with_meta`。

**AB9**: SHM inference path FORBIDDEN。 不允许 `gicg_actor/inference_shm_client.go` / `InferenceShmBridge` 等 cross-process SHM inference 桥层。 pre-R7 已删 (R7.1)。 任何 future inference 提案 SHALL 走 socket pattern 或证明零 bridge layer。

### 3.4 ClientID semantic

**AB10**: 每 Go actor subprocess SHALL 显式分配 `Config.BaseActorID` (≥ 0,unique across the N subprocesses);其内部 actorID = `BaseActorID + local_idx`。 N independent subprocess 各 `NActors=1` 时 actorID == BaseActorID == subprocess index。 assembler 端 `(clientID, episode_id)` 作 key,BaseActorID 唯一性保证 cross-subprocess key 无冲突。

### 3.5 Atomic spawn + shutdown

**AB11**: `spawn_pipeline` SHALL atomic — 任一 step (InfServer start / SHM ring create / Go subprocess spawn) 失败 SHALL cleanup 已 spawn 的所有 component。 partial-spawn 残留禁止。

**AB12**: shutdown 顺序 SHALL 严格:
1. N parallel SIGTERM 到 N Go subprocess (`os.kill` non-blocking)
2. Sequential wait join 每个 subprocess (each `terminate(timeout_s)` call,timeout per process,不累积)
3. Trans channel close (shared SHM unlink)
4. InferenceServer stop

不允许 Step 2 / Step 4 早于 Step 1 — Go subprocess in-flight inference 仍可能向 InfServer 发请求,InfServer 早死 → Go socket EOF panic。

## 4. Code references

**Implementation entry points** (post-R7 ship):
- `training/paradigms/dmc/paradigm.py:_make_go_collector` — dispatch hook (AB1-AB3)
- `training/paradigms/dmc/go_subprocess_collector.py:DMCGoSubprocessCollector` — DMC collector adapter
- `training/core/actor/go_subprocess_pipeline.py:spawn_pipeline` — atomic N subprocess spawn (AB4 / AB11)
- `training/core/actor/go_subprocess_pipeline.py:PipelineHandle.shutdown` — shutdown 顺序 (AB12)
- `training/core/actor/go_subprocess.py:GoSubprocessHandle` — per-subprocess lifecycle
- `cmd/gicg_actor/main.go` — Go subprocess entry (parseConfig + READY signal + paradigm.Run dispatch)
- `gicg_actor/pool.go:Config` — BaseActorID + NActors=1 (AB10)
- `gicg_actor/pool.go:Run` — paradigm.Run wrapper
- `training/core/actor/inference_server.py:_socket_listener` — socket accept thread (AB7)
- `training/core/actor/transition_shm_channel.py` — MPSC SHM ring wrapper (AB8)

**Test references**:
- `training/paradigms/dmc/tests/test_go_subprocess_5ep_e2e.py` — 5 ep e2e (AB4 / AB5 verified via ps grep)
- `training/core/actor/tests/test_go_subprocess_spawn.py` — spawn/READY/terminate cycle
- `training/core/actor/tests/test_go_subprocess_perf_smoke.py` — smoke_full perf gate (Mac N=4 fps/actor ≥ ratio threshold)
- `tools/_bench/run_mac_collector_pair.py` — Mac fair bench harness (per [[i29-bench-harness]])

**Cfg references**:
- `configs/dmc/bench_v_legacy_mac_python_mp.toml` + `bench_v_legacy_mac_go.toml` — fair bench cfg pair (双侧 `minimax_node_budget=4000` algorithm 对齐)

## 5. Status

Created 2026-05-25 (post R7 ship,commit `a4da6d1`)。

Revision triggers:
- 新 paradigm 接 `actor_backend='go'` (AZ/PPO/CFR/BC port,Phase 2 follow-up) — AB3 status table update
- Win box gate 关 (audit I1) — 加 Win bench verify reference
- Production no-cap fair bench ship — 加 cgo-dominated workload ratio data point
- 新 inference transport 提案 (e.g. unix domain socket,Linux io_uring) — AB7 / AB9 review

## 6. Cross-references

- Parent: [`./spec.md`](./spec.md) (capability SHALL #1-17)
- Sibling: [`./protocols.md`](./protocols.md) Collector / NetworkProvider — actor backend 实现 collector protocol
- Sibling: [`./pipeline.md`](./pipeline.md) — driver loop 调 collector.collect
- Sibling: [`./network-sharing.md`](./network-sharing.md) — InferenceServer 端 batched forward + decoder_path
- Memory: [[i29-r7-acceptance-ship]] / [[python-arch-mimicry-for-go-port]] / [[i29-bench-harness]] / [[bench-variance-5seed-required]]
- Archive: `openspec/changes/archive/0006-i29-go-actor-pool/` (pre-redesign cgo path STATE_DUMP + lesson)
- Archive: `openspec/changes/i29-r7-n-subprocess/` (R7 ship change,待 archive)
