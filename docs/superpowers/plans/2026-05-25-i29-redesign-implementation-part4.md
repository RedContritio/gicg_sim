> 分卷导航:回到 [← Part 1](2026-05-25-i29-redesign-implementation.md) · [← Part 2](2026-05-25-i29-redesign-implementation-part2.md) · [← Part 3](2026-05-25-i29-redesign-implementation-part3.md)

## Phase 1 — N actor + DMC paradigm wiring + 5 episode e2e

**Goal:** DMC paradigm 完整 hookup 到新 architecture,N actor 同时 push 真 wire v3 transition,5 episode e2e PASS,subprocess clean shutdown。

**Exit gate:** Mac N=4 跑 5 episode buffer fill 数对 (期望 transitions ≈ 5 × ~340 / 16 batched);Go subprocess SIGTERM 后 exit 0;无 SHM leak (ipcs / lsof check 无残留)。

### Task 1.1: 删旧 cgo singleton + Run(ctx, cfg) 单次调用模式

**Files:**
- Modify: `gicg_actor/pool.go` — 提取 `Run(ctx, cfg) error` 函数,actorLoop 不变,删全局 singleton (var mu, running, cancel, ...) 但 retain backward-compat 期间不删 capi/ 路径 (P3 才删)
- Refactor: `cmd/gicg_actor/main.go` — 改调 `gicg_actor.Run(ctx, cfg)` 取代 inline placeholderActor

(Subagent task,详步骤见下方 Subagent Brief)

**Subagent Brief (P1.1):** 见本 plan 末尾「Subagent dispatch briefs」段。

### Task 1.2: TransitionWriter 改 SHM (替 TCP)

**Files:**
- Create: `gicg_actor/transition_writer_shm.go` — SHM transition writer (实现 同 `TransitionWriter` 接口的 SHM 版)
- Create: `gicg_actor/transition_writer_shm_test.go` — unit + cross-lang test
- Modify: `gicg_actor/pool.go` (或 cmd/gicg_actor/main.go) — 调 shm writer 取代 TCP writer

**Subagent Brief (P1.2):** 见末尾。

### Task 1.3: DMC paradigm hookup 到 N goroutine + 真 InfServer TCP inference

**Files:**
- Modify: `cmd/gicg_actor/main.go` — Config 加 paradigm_name + paradigm_config + inf_server_addr;调 `gicg_actor.Run` 真启 DMC paradigm
- Modify: `training/core/actor/go_subprocess.py` — `spawn` Config 加 paradigm 字段透传

**Subagent Brief (P1.3):** 见末尾。

### Task 1.4: 5 episode e2e (master spawn subprocess + Go run DMC + master 收 trans + buffer ingest verify)

**Files:**
- Create: `training/paradigms/dmc/tests/test_go_subprocess_e2e.py` — 完整 e2e:Python InfServer subprocess + Go-actor subprocess + 5 ep + buffer fill verify
- Modify: `training/paradigms/dmc/go_collector.py` — `collect()` 改 `transition_shm_channel.try_pop` (替 listener queue)

**Subagent Brief (P1.4):** 见末尾。

---

## Phase 2 — Mac fair bench acceptance (本设计 verify gate)

**Goal:** Mac N=4 × 5 seed × 2 backend fair bench,Go fps/actor mean ≥ Python mp 48.1 × 1.00,std/mean ≤ 25%。

### Task 2.1: 适配 `tools/_bench/run_mac_collector_pair.py` 到新 backend

**Files:**
- Modify: `tools/_bench/run_mac_collector_pair.py` — 新 Go test node = `training/core/actor/tests/test_go_subprocess_perf_smoke.py::test_go_subprocess_perf_smoke_15s`
- Create: `training/core/actor/tests/test_go_subprocess_perf_smoke.py` — 15s collector smoke,接 `BENCH_N_ACTORS` / `BENCH_SEED` env,打 `[perf smoke] elapsed=... fps=... fps/actor=... delta=...MB decode_errors=0` 行

### Task 2.2: 跑 Mac fair bench 5 seed × 2 backend × N=4

```bash
.venv/bin/python -m tools._bench.run_mac_collector_pair --n-actors 4 --seeds 5 --out tools/_bench/p2_acceptance.md
```

### Task 2.3: Verify gate

**PASS condition:** `go.fps_per_actor_mean ≥ 48.1 × 1.00` AND `go.fps_per_actor_std / go.fps_per_actor_mean ≤ 0.25`

**FAIL handling:**
- 若 fps < 48 但 ≥ 36 (75% baseline):dispatch opus subagent root-cause + suggest fix,P2 重跑
- 若 fps < 36 (< 75%):结构性问题,落 STATE_DUMP + 暂停 + 待 user 决

### Task 2.4: Commit acceptance result

成功:落 `tools/_bench/p2_acceptance.md` + commit + `STATE_DUMP` 关 I29 重设计。
失败:落 acceptance fail report + 进入 root cause subagent 调查 loop。

---

## Phase 3 — 旧 cgo path 退役 + regression test 切换

**Goal:** 删 `gicg_actor/capi/` + 删 `transition_sink_listener.py` + `go_collector.py` 全切 SHM path + 全仓 pytest PASS。

### Task 3.1: 删 `gicg_actor/capi/` + 相关 build script

**Subagent Brief (P3.1):** 见末尾。

### Task 3.2: 删 `transition_sink_listener.py` + `go_backend.py` cgo 路径

**Subagent Brief (P3.2):** 见末尾。

### Task 3.3: 全仓 pytest + smoke regress

```bash
.venv/bin/python -m pytest -n 4 training/ gicg_env/ -q --tb=short
.venv/bin/python -m pytest -m smoke training/tests/ -q
```

**Expected:** 全 PASS (其他 4 paradigm 不动,只 DMC 切 SHM path)。

### Task 3.4: Final commit + 归档

---

## Subagent dispatch briefs

(每个 subagent 用 opus model;每 task 单 brief,自包含 file paths + 已有约束 + 期望产出)

### P1.1 Brief — pool.go refactor 为 Run(ctx, cfg) error

**Context:** 当前 `gicg_actor/pool.go` (310 LOC) 是 c-shared lib 全局 singleton 模式 (var mu, running, cancel, currentInfReqs, currentTWs, aliveActors)。 I29 redesign 改用 `cmd/gicg_actor` standalone executable,不再需要 singleton (一个 process 只跑一次 Run)。 但 `gicg_actor/capi/` 仍 build 中 (P3 才删),所以 pool.go 保留 backward-compat,提取 `Run(ctx, cfg) error` 内核函数,singleton 路径调本函数。

**Task:** 重构 `gicg_actor/pool.go`:
1. 提取 `Run(ctx context.Context, cfg Config) error` — 接受 context,起 N goroutine 跑 paradigm.Run,wg.Wait,返回 nil/err
2. 现有 `StartPoolWithConfig(cfg) int` 改成 wrapper:goroutine background 调 `Run`,保 backward-compat
3. `StopPool()` 仍用 singleton cancel,保 backward-compat
4. **不动** capi/ 任何函数
5. `cmd/gicg_actor/main.go` 调 `gicg_actor.Run(ctx, cfg)` 替原 inline actorLoop

**Constraints:**
- All Go tests in `gicg_actor/` 必须 PASS (`go test ./gicg_actor/... -v`)
- cmd/gicg_actor build OK (`go build -o bin/gicg_actor ./cmd/gicg_actor`)
- `training/core/actor/tests/test_go_subprocess_*.py` 全 PASS

### P1.2 Brief — TransitionWriter SHM 实现

**Context:** 当前 `gicg_actor/transition_writer.go` 是 TCP socket writer,master 端 `training/core/actor/transition_sink_listener.py` 接。 I29 redesign 改 SHMRing,Go side 写新 `transition_writer_shm.go` 实现 SHM push,paradigm `paradigm.Run` 接收 interface `TransitionSink` (重命名 from `*TransitionWriter` 为 interface),两实现可换。

**Task:**
1. 抽 `TransitionSink interface { Push(payload []byte, isEpisodeEnd bool) error; Close() error }`(API 与现有 TransitionWriter 兼容)
2. 实现 `TransitionWriterShm` (struct over shm writer wrapper) — `Push` 调 SHM ring push,full 时 spin + sched_yield 直到 ctx done 或 success
3. `paradigm.Run` signature 改接 `TransitionSink` 接口
4. cmd/gicg_actor `Run` 调用时传 SHM 实现;capi/ 仍传 TCP 实现 (backward-compat)

**Tests:**
- `gicg_actor/transition_writer_shm_test.go` — push + Python ring_shm pop verify cross-lang

### P1.3 Brief — DMC paradigm full hookup

**Context:** P0.4 已证 SHM 通,P1.1+P1.2 已 refactor pool/writer。 现把 DMC paradigm.Run 真 wire 进新架构:Config 接 paradigm_name + paradigm_config JSON + inf_server_addr,cmd/gicg_actor 起 N goroutine 跑 DMC paradigm。

**Task:**
1. cmd/gicg_actor/main.go: Config 加字段 + `gicg_actor.Run` 调用传完整 cfg
2. training/core/actor/go_subprocess.py: spawn cfg dict 透传 paradigm_*
3. 1 actor smoke: master spawn → Go 跑 DMC 1 episode → push 真 wire v3 trans → master decode verify obs shape 对

**Tests:**
- `training/paradigms/dmc/tests/test_go_subprocess_1ep_smoke.py` — 1 ep 真 InfServer TCP inference + 真 game loop + trans decode shape verify

### P1.4 Brief — 5 episode e2e + go_collector.py 适配

**Context:** 现有 `training/paradigms/dmc/go_collector.py` 用 `transition_sink_listener` (TCP listener queue 路径)。 改成 try_pop SHMRing 路径。

**Task:**
1. go_collector.py: `__init__` 接 `TransitionShmChannel` 实例 + `GoSubprocessHandle`;`collect()` 走 `ch.try_pop_with_meta` + `_go_assembler.ingest`;删 listener / handler ref
2. 5 ep e2e test 跑通

**Tests:**
- `training/paradigms/dmc/tests/test_go_subprocess_e2e.py` — full pipeline 5 ep PASS

### P3.1 Brief — 删 gicg_actor/capi/

**Context:** P2 acceptance gate PASS 后,旧 cgo path 已无人调用 (cmd/gicg_actor standalone path 全替代)。 删 `gicg_actor/capi/` + build script + ctypes load 路径。

**Task:**
1. 删 `gicg_actor/capi/` 整目录 (含 main.go capi exports)
2. 删 `gicg_env/libgicg_actor.{dylib,dll}` 旧 build artifact
3. 删 `gicg_actor/pool.go` 的 backward-compat 包装 (StartPoolWithConfig / StopPool / AliveCount singleton path)
4. `gicg_actor/Run(ctx, cfg)` 保留 (cmd/gicg_actor 调它)

### P3.2 Brief — 删 transition_sink_listener + cgo load 路径

**Context:** 旧 master 端 cgo + TCP listener 路径已 abandon。

**Task:**
1. 删 `training/core/actor/transition_sink_listener.py`
2. `training/core/actor/go_backend.py` 整文件改 `GoSubprocessBackend` (薄 wrapper over `GoSubprocessHandle` + `TransitionShmChannel`)
3. `training/paradigms/dmc/go_collector.py` 引用更新
4. 全仓 pytest PASS

---

## Self-Review

**Spec coverage check:**
- spec §3 deal-breaker (1) master 0 IPC threads → P3.2 删 transition_sink_listener + capi cgo load ✓
- spec §3 deal-breaker (2) transition 跨进程 shm → P0.3 + P1.2 ✓
- spec §3 deal-breaker (3) foundation-first ≤ 300 LOC verify → P0 (~250 LOC) + Exit gate ✓
- spec §4.2 components 全 covered (cmd/gicg_actor / go_subprocess.py / transition_shm_channel.py / pool.go refactor / transition_writer SHM / go_backend rewrite / capi 退役)
- spec §4.3 data flow 三阶段 (启动 / 运行 / 关闭) 全 covered
- spec §4.4 error handling 5 row 全 covered (subprocess fail / actor fatal / SHM full / master SIGKILL / InfServer down)
- spec §4.5 testing strategy unit + integration + Mac fair bench 全 covered
- spec §5 phase budget 750 LOC 总,本 plan 也是 P0 250 + P1 250 + P2 100 + P3 150 ✓
- spec §6 out-of-scope (Win / AZ-PPO-CFR-BC port / InfServer 内部 / 长跑 mem 深优 / 历史对手 ring) 本 plan 未触 ✓

**Placeholder scan:** 通过 — 每 task 含实代码/命令/期望输出,无 "TBD / TODO"。 注意 P1.1-P1.4 + P3.1-P3.2 用 "Subagent Brief" 模式委派,subagent 自含细节 (符合 user 「subagent-driven dev」要求)。

**Type consistency:** TransitionShmChannel.try_pop_with_meta 返 `(int, int, bytes)` — 各 test 用同签名 ✓。 GoSubprocessHandle.spawn API 一致 (classmethod 返 instance,`.alive() / .terminate() / .returncode`)。

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-25-i29-redesign-implementation.md`。

**执行方式:Subagent-Driven (用户已 explicit 授权 + subagent 全 opus)。**

REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`

Fresh opus subagent per task + two-stage review (implementer → reviewer):
- P0.1-P0.2: 简单 LOC,可直跑 (无需 subagent)
- P0.3 onwards: subagent dispatch opus
- 每 task commit + verify gate 通过后 → 下一 task
- Phase 间显式 verify (`pytest` / `go test` / smoke) 不通过不进下一 phase
