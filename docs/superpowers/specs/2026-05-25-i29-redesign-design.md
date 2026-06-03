# I29 Go-actor pool 完全重设计 — Mac perf gate design (2026-05-25)

> ⚠ **SUPERSEDED — 描述的是 R1 初版 "3 OS process" 架构,not shipped R7 (N+2 = N independent Go subprocess)**。 本 design 节 §4.1 "3 OS process" 不再适用。 实际 ship architecture 见:
> - `openspec/changes/archive/i29-r7-n-subprocess/` (post-ship proposal + design + tasks)
> - `openspec/specs/training-architecture/actor-backend.md` (SHALL contract AB1-AB12)
> - `docs/superpowers/specs/2026-05-25-i29-redesign-pr-draft.md` (final acceptance summary)
>
> 留作历史 trail (R1 candidate path → audit → R7 emergent fix)。 不要据此本 doc 推断 production architecture。

## 1. Goal

Mac 端 Go-actor 在 fair benchmark 下 fps/actor 均值 ≥ Python mp 基线均值,在统一 commit / 配置 / 硬件 / 同 harness 同 seed 下成立。

非目标:Win 平台不在本设计验收范围 (memory: `feedback_default_mps` Win+cu130 平台限制单独追);AZ/PPO/CFR/BC paradigm port 不在本设计范围 (DMC 通过后另立)。

## 2. 现状 + Root cause (背景)

完整状态归档:`openspec/changes/i29-go-actor-pool/STATE_DUMP_2026_05_24.md`。

本设计与之前 3 branch (Phase A / T-B1 / F1 / SHM Path A,累 1890 LOC) 的本质差异:

**Root cause 已 verified**:整个 Go-actor pool 跑在 Python master process 内 (cgo loaded library + N goroutine + IPC threads),master 既是训练 driver,又是 IPC hub (transition_sink_listener / handler threads / 之前的 ShmBridge daemon)。Mac N=4 实测 Go 12.75 fps/actor 仅为 Python mp 48.11 fps/actor 的 26%;Python mp 把每个 actor 隔到独立 OS subprocess,master 完全不参与 IPC,只 train + buffer ingest (SHMRing.try_pop 轻活)。

之前所有优化 (T-B1 mutex 拆 / F1 episode-granularity push / SHM Path A) 都是局部 transport 优化,未触此 architectural flaw。

## 3. 本设计核心 invariant (deal-breakers)

(三条均直接来自 STATE_DUMP §9,这次必须满足)

1. **master process 0 IPC threads** — 不允许 cgo loaded Go runtime 跑 master process 内;不允许 listener / handler / bridge daemon 持 master GIL。Master 仅:训练 loop + SHMRing.try_pop 读 transition。
2. **transition / weights / control 跨进程走 shm-backed channel** — 现有 SHMRing infra (Phase 1-4 cross-lang verified PASS) 复用。
3. **foundation-first ≤ 300 LOC 即可 fair bench verify** — 在大改造之前先证明架构能 ≥ Python mp,不再 1500 LOC 后才发现错。

## 4. Architecture

### 4.1 Process topology (target)

```
┌───────────────────────────┐
│ Master Python process     │
│  - driver train loop      │
│  - buffer (在 master)      │
│  - SHMRing.try_pop ×1     │ ← 轻活,driver 偶尔 poll
│  ※ 不 load 任何 cgo lib    │
└───────────────────────────┘
         ↑ SHMRing trans
         │ (cross-process shm)
┌───────────────────────────┐    ┌─────────────────────────┐
│ Go-actor subprocess (1)   │    │ InfServer subprocess (1)│
│  独立 OS process           │ → TCP → │ batched forward     │
│  含 N goroutine actor      │ ← TCP ← │ socket_listener     │
│  Go runtime native        │    │ + GPU forward loop      │
│  无 Python GIL contention │    └─────────────────────────┘
└───────────────────────────┘
```

启动数:**3 OS process** (1 master + 1 Go-actor subprocess + 1 InfServer subprocess),不论 N actor 多少。Python mp 是 (N+2) process。

### 4.2 Components

**新增**:

- `cmd/gicg_actor/main.go` — standalone Go executable entry。从 stdin 读 `Config` JSON 一次 → 起 N goroutine actor → 进入 paradigm.Run loop → SIGTERM 优雅退出。**不再** build c-shared lib 给 Python ctypes load (现有 `gicg_actor/capi/` 留作过渡期参考,本设计完成后删)。
- `training/core/actor/go_subprocess.py` — Python 侧 master spawner。`spawn(cfg) -> SubprocessHandle`:
  - subprocess.Popen Go executable,传 SHM names via stdin Config JSON
  - 等 subprocess ready signal (stdout 一行 `READY\n`)
  - 提供 `wait_ready / alive / terminate / join` API
  - 负责 SHMRing transition 的 master 端 attach (owner) + cleanup (unlink on master exit)
- `training/core/actor/transition_shm_channel.py` — 复用 `training/core/actor/ipc/ring_shm.py`,封 N-producer (Go-side N goroutine) 单 ring → 1-consumer (master driver) try_pop 模式。

**改动**:

- `gicg_actor/pool.go` — 砍 `var (mu, running, cancel, ...)` 全局 singleton 模式;改成 `Run(ctx, cfg) error` 单次调用流。`actorLoop` 不变 (已经是 per-actor goroutine),只是 lifecycle 由 cmd/gicg_actor/main.go 持。
- `gicg_actor/transition_writer.go` — 改 SHMRing push (替代现有 TCP socket)。复用 wire v3 binary layout,只换 transport。
- `gicg_actor/inference_client.go` — **不动**。Go-actor subprocess ↔ InfServer subprocess 仍走现有 TCP path (proven,无 GIL 问题因为双方都是非 Python OS process)。
- `training/core/actor/go_backend.py` — 砍 `ctypes.CDLL("libgicg_actor.dylib")` 路径;改 `GoSubprocessBackend` (本设计新增 class) 跑 spawn → wait_ready → 持有 handle → atexit terminate。
- `training/core/actor/transition_sink_listener.py` — 砍 (TCP listener 不再需要)。
- `training/paradigms/dmc/go_collector.py` — `collect()` 改 `transition_shm_channel.try_pop` + `_go_assembler.ingest`,删 listener / handler thread refs。
- `gicg_actor/capi/` — 整目录砍 (cgo build path 退役)。

**保留不变**:

- `gicg_actor/shm/` — POSIX + Win SHM ring 底层 (Phase 1-4 已 verified PASS,跨平台 unified)
- `training/core/actor/ipc/ring_shm.py` — Python ctypes wrapper for SHMRing
- `training/core/actor/inference_server.py` — InfServer subprocess (现有 Python mp 路径就用它,无改动需要)
- 所有 `gicg_actor/dmc/` paradigm logic (game loop / opponent / observation encoder)
- wire format v3 (已 verified 跨平台 nlegal-sized payload, ~12 KB/transition)

### 4.3 Data flow

**启动序列** (master spawns Go-actor subprocess):

```
Master:
1. allocate SHMRing trans (N-producer 单 ring,cap=4096,slot=16KB)
   → trans_ring_name = "gicg_trans_<pid>"
2. spawn InfServer subprocess (现有路径)
   → infserver_port = NNNN
3. spawn Go-actor subprocess:
   subprocess.Popen(["./cmd_gicg_actor"], stdin=PIPE, stdout=PIPE)
   → write Config JSON {n_actors, paradigm, paradigm_cfg, infserver_addr,
                        trans_ring_name, trans_ring_cap, trans_slot_size}
   → wait stdout line "READY\n" (Go side attach SHM + connect InfServer + N goroutine started)
   → 超时 30s fail-loud (subprocess.terminate + raise)
4. driver loop 开始
```

**运行期** (每 transition):

```
Go goroutine[i]:
  game.step → encode wire v3 → trans_writer.shm_push(payload)
                                     (lock-free MPSC ring, ~µs scale)

Master driver loop:
  while training:
    train_step()  ← 大头 GPU forward (49ms × ~8/s)
    if iter % collect_interval == 0:
       items = trans_ring.drain_n(max=128)  ← 轻活,~µs
       for it in items: assembler.ingest(it) ← 解 payload + buffer push
```

**关闭序列**:

```
Master atexit:
1. subprocess.terminate (SIGTERM) Go-actor
2. Go side: signal handler → ctx.Cancel → wg.Wait → close inf conn → drain SHM → exit 0
3. master joins subprocess (timeout 10s,超时 SIGKILL)
4. unlink SHMRing trans (owner-only API)
5. terminate InfServer subprocess (SIGTERM,timeout 10s 后 SIGKILL,同 Go-actor 收尾)
```

### 4.4 Error handling

| 失败模式 | 现行 (前 I29) | 本设计 |
|---|---|---|
| Go subprocess startup fail | cgo Go panic → process abort | subprocess exit ≠ 0 → master raise fail-loud,subprocess stderr 完整 capture |
| Go actor goroutine fatal | 静默 panic + AliveCount 减 | subprocess stdout 报 `ACTOR_FATAL id=N err=...\n` → master log + alive_count |
| SHMRing trans 满 | TCP backpressure 阻塞 push | Go side `shm_push` block (lock-free spin + sched_yield),Python try_pop 拖慢 → backpressure 自然 |
| Master SIGKILL | Go runtime hang (no signal handler) | subprocess 自带 SIGTERM handler 已存在 (memory: `feedback_go_cgo_signal_handler`);master 死后 subprocess 由 OS 收 (parent_pid==1 后自杀 via prctl PR_SET_PDEATHSIG on linux,Mac 用 kqueue EVFILT_PROC) |
| InfServer down | TCP recv timeout → Go raise | 同 (不变,InfServer subprocess 已 proven path) |

### 4.5 Testing strategy

**Unit** (Go):
- `cmd/gicg_actor/main_test.go` — Config JSON parsing + SHM attach error paths
- `gicg_actor/transition_writer_shm_test.go` — push N items + read back via shm test peer (mock master)

**Unit** (Python):
- `training/core/actor/tests/test_go_subprocess_spawn.py` — spawn → wait_ready → terminate cycle
- `training/core/actor/tests/test_transition_shm_channel.py` — N-producer ring → 1-consumer ingest

**Integration** (cross-lang):
- `training/paradigms/dmc/tests/test_go_subprocess_e2e.py` — 真 spawn Go subprocess + InfServer + run 5 episodes + verify buffer fill + clean shutdown
- (替换现有 `test_go_collector_e2e.py` 的 cgo path)

**Mac fair bench** (acceptance gate):
- `tools/_bench/run_mac_collector_pair.py` (已存在,需小改适配新 backend)
- Mac N=4 × n_runs=5 × seed (1,2,3,4,5),Python mp vs Go subprocess 同 cfg / 同 commit / 同硬件 / 同 harness 串行执行
- 接受: Go fps/actor mean ≥ Python mp fps/actor mean × 1.00,std/mean ≤ 25%
- Mac N=8 不作 gate (Python mp N=8 实测已 InfServer CPU 饱和,Mac CPU 限制),仅 scaling reference

(Foundation-first PoC 见 §5 Phase 0,exit gate 即 fps/actor ≥ Python mp single-actor baseline)

## 5. 实施阶段化 (foundation-first)

| Phase | 范围 | LOC est | Exit gate |
|---|---|---:|---|
| **P0 — 200 LOC PoC** | cmd/gicg_actor stub + master spawn + 单 actor + SHMRing trans + 60s Mac smoke | ~250 | Mac N=1 fps ≥ Python mp N=1 fps (single-actor 对照),无 GIL contention,无 leak |
| **P1 — N actor + paradigm wire** | DMC paradigm.Run hookup + N goroutine + N-producer SHMRing + 真 InfServer + 5 episode e2e | ~250 | Mac N=4 e2e 5 ep buffer fill correct,Go process clean shutdown |
| **P2 — Mac fair bench acceptance** | `run_mac_collector_pair.py` 适配 + 5 seed × 2 backend Mac bench + verify gate | ~100 | **本设计验收 gate**:Mac N=4 fps/actor mean ≥ 48.1 (Python mp baseline) × 1.00,n=5 runs,std/mean ≤ 25% |
| **P3 — 旧 cgo path 退役 + integration test 切换** | 删 `gicg_actor/capi/`,删 `transition_sink_listener.py`,go_collector.py 全切 SHM path,test_go_collector_e2e.py 改 subprocess path | ~150 | 全仓 pytest 1156+ PASS,smoke 全 5 paradigm PASS (其他 4 paradigm 仍走旧 Python mp,无 regression) |

**总 LOC budget**:~750 (vs 之前 3 branch 累 1890)。

**每 phase 必须**:fair bench / smoke 跑通 + commit + 数据落 `tools/_bench/` 才进下一 phase。

## 6. Out of scope

- Win 平台 fair bench (Mac gate 达成后另立,Win+cu130 平台限制单独追踪)
- AZ/PPO/CFR/BC paradigm port (DMC 通过后另立;CFR/BC 仍 D12 决策不 port)
- InfServer 内部优化 (batching window / GPU pipeline)
- 长跑 mem 优化 (本设计只验证 fps gate;mem 在 Phase 2 acceptance 时设松 gate 防 leak,不深优)
- 历史对手 ring (D10 决策 cut)

## 7. Open questions (设计 review 时定)

1. Go subprocess 与 master 共享同一 venv 还是独立 binary?**默认**:独立 binary (build 后 `./bin/gicg_actor` 或类似),master Popen 直接调,无 venv 依赖。
2. SHMRing trans 容量?**默认**:cap=4096 × slot_size=16KB (= 64 MB total),够 N=16 × 6.86 push/s 下 ~5 分钟 backlog。
3. 控制平面 (动态调参 / weights reload):本设计**不动**,沿用现有 `weights_shm.py` 路径 (master 写 shm,Go 周期 poll)。

## 8. 失败教训防范 (本设计 explicit guard)

| 之前教训 | 本设计 guard |
|---|---|
| 1500 LOC 后才发现错 | Phase 0 200 LOC 即 verify |
| sub-agent 用 sonnet 漏 cgo / errno 等 | 本设计实施全用 opus model (memory: `feedback_subagent_model_selection`) |
| perf claim 不 fair bench | Phase 2 acceptance = fair bench gate,n=5 seed,串行同硬件 |
| Mac 单 run variance huge 不可靠 | n=5 runs + std/mean ≤ 25% 双 gate |
| silent decision | 本 spec 显式列 deal-breaker / acceptance / out-of-scope;Phase 间 commit gate user review |

## 9. 关联文档

- `openspec/changes/i29-go-actor-pool/STATE_DUMP_2026_05_24.md` — 完整状态归档 (本设计前提)
- `openspec/changes/i29-go-actor-pool/shminf_design.md` — Phase 1-4 cross-lang SHMRing design (本设计复用)
- `tools/_bench/mac_collector_results.md` — Mac N=4 fair bench baseline (本设计 verify 目标)
- memory: `feedback_performance_must_verify` / `feedback_subagent_model_selection` / `feedback_cfg_driven_only`
