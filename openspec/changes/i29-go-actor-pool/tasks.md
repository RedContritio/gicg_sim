# Tasks — I29 Go actor pool

4 phase 顺序 ship。 每 phase 末 verify gate 通过才进下一 phase(标 `[blocker]`)。 边界硬约束:
**`gicg_engine/` 零侵入**(post-P1.2c 起 `gicg_engine/factory/` 是 engine 包族内 refactor
不算破坏边界,RL 概念仍在 `gicg_actor/`)。 所有 RL 代码进新顶层 `gicg_actor/`。

## Phase 0 — scaffold(~250 LOC)— DONE 2026-05-19

- [x] T-0.1 创建顶层 `gicg_actor/` package(跟 `gicg_engine/` 并列)+ 空 `pool.go`
- [x] T-0.2 `gicg_actor/capi/main.go` + 最小 C API
- [x] T-0.3 build 命令验证(Mac);Win PowerShell 同模板
- [x] T-0.4 SIGTERM handler
- [x] T-0.5 `training/core/actor/go_backend.py` ctypes wrapper minimal
- [x] T-0.6 atexit hook
- [x] T-0.7 hello-world test PASS Mac
- [x] T-0.8 `libgicg` 不受影响 smoke PASS
- [x] T-0.9 跨平台 build CI(Mac verified;Win 走 P1.5)
- [x] T-0.10 Phase 0 verify 全过 [blocker]

## Phase 1 — production e2e(实际 ship ~3300 LOC across 8 commit batches 2026-05-22)

注:本 phase 是单大 PR,内部按 T-1.X 顺序 develop + 合并前 verify。 risk 高(2000+ LOC 一次性 ship),
但 user 明确不接受 mock 中间态。

### P1.1 Go actor 主体(paradigm-agnostic,~800 LOC)— DONE

- [x] T-1.1 `gicg_actor/pool.go`:N goroutine 调度,生命周期 start/stop
- [x] T-1.2 `gicg_actor/episode.go` 整合到 dmc/paradigm.go(paradigm owns 完整 lifecycle)
- [x] T-1.3 `gicg_actor/adapter.go`:Paradigm interface(含 Configure)+ 注册表
- [x] T-1.4 `gicg_actor/inference_client.go`:TCP localhost socket 客户端,raw bytes wire format
- [x] T-1.5 `gicg_actor/transition_writer.go`:transition push socket(D7 修正落实)
- [x] T-1.6 Go unit tests(socket round-trip + wire format)

### P1.2 DMC paradigm adapter(~600 LOC)— DONE

- [x] T-1.7 `gicg_actor/dmc/obs_encoder.go`:port `_capture_obs_np` + `_encode_static_np` 到 Go
- [x] T-1.8 `gicg_actor/dmc/obs_encoder_test.go`:数值等价测(unit;cross-lang bit-exact 走 P1.5)
- [x] T-1.9 `gicg_actor/dmc/greedy_player.go`:F1-F5 × D1-D4 完整 port
- [x] T-1.10 `gicg_actor/dmc/greedy_player_winrate_test.go` winrate gate(F1-D1 random baseline)
- [x] T-1.11 DMC adapter 注册(走 init() 自动)
- [x] **P1.2c**(blocker,2026-05-22):engine factory refactor(capi/initGame → factory/NewGame)
      让 `gicg_actor/` 可 import `gicg_engine/factory.NewGame` native call,无 cgo overhead

### P1.3 InfServer accept Go socket(~150 LOC Python)— DONE

- [x] T-1.12 inference_server.py socket_port + socket_forward_builder_path 集成,listener
      thread 在 InfServer 子进程内启动,闭包共享 network + shared_cache
- [x] T-1.13 InfServer socket protocol 单测(test_inference_server_socket_integration.py)

### P1.4 Python backend wiring(~900 LOC across 9 commits)— DONE

- [~] T-1.14 ActorBackend Protocol — DEFERRED 到 P2(DMC Go path 已闭环,Protocol 抽象 ROI 在
      P2 多 paradigm 时显现)
- [~] T-1.15 PythonActorBackend — DEFERRED 同 T-1.14
- [x] T-1.16 GoActorBackend.start_with_config — ctypes start_pool_v2 + paradigm_cfg JSON 传递
- [x] T-1.17 transition_sink_wire + listener + DMC self-contained payload(自包含 transition
      含 dyn + refs + pay + static for first transition,N* 字段 u32 防 overflow)+ Python
      DmcTransitionAssembler 重组 episode → DmcTransition + winner
- [x] **P1.4i**(2026-05-22):DMCGoActorCollector 闭环 — InferServer + socket listener +
      GoActorBackend + TransitionSink + DmcTransitionAssembler 5 组件绑成 Collector,
      实现完整 collect / sync_weights / close / state_dict 协议,e2e smoke 验证
      DmcTransition obs_dict 16 字段全在 + winner ∈ {-1, 0, 1}
- [~] T-1.18 cfg.pipeline.actor_backend schema — DEFERRED 到 P2 多 paradigm 时一起 ship

### P1.5 Mac smoke verify + Win box prep — MAC DONE / WIN 待 USER 实测

- [x] **Mac perf smoke 2026-05-22**:N=4 actor 15s window
      · 30.83 fps total = 7.71 fps/actor(Python baseline ~4.4/actor → ~1.75x 加速)
      · mem delta +263 MB(< 500 MB threshold)
      · decode_errors = 0(wire 协议 self-consistency 守)
      · 30 episodes assembled,0 deadlock
- [x] T-1.19 build 命令文档化(本文件下方 P1.5-doc)
- [ ] T-1.20 Win box stress test:`pytest training/core/actor/tests/test_go_actor_perf_smoke.py
      -m smoke_full` after sync + build。 调 N=16 actors 验证
- [ ] T-1.21 fps 实测对照:N=16 Go backend fps 应 ≥ 70(本 perf smoke Mac N=4 = 30.8 fps,linear
      scale 估 N=16 ≥ 120 fps,但 InfServer 单 thread forward 可能成新瓶颈,实测才知)
- [ ] T-1.22 mem 实测对照:N=16 master RSS Go ≤ 2 GB
- [ ] T-1.23 Phase 1 verify:obs bit-exact + opp winrate gate + N=16 Win fps ≥ 70 + mem ≤ 2 GB 全过
      [blocker]

### P1.5-doc:Win box smoke 步骤(post-P1.4g)

1. sync branch `feature/tools-runs-fixes` 到 Win box:
   ```powershell
   # 在 Win box PowerShell
   cd D:\gicg_dev
   git fetch origin
   git checkout feature/tools-runs-fixes
   git pull
   ```

2. build 两份 c-shared:
   ```powershell
   $env:CGO_ENABLED = "1"
   $env:CC = "C:\Strawberry\c\bin\gcc.exe"
   $env:PATH = "C:\Strawberry\c\bin;" + $env:PATH
   go build -buildmode=c-shared -o gicg_env\libgicg.dll .\gicg_engine\capi
   go build -buildmode=c-shared -o gicg_env\libgicg_actor.dll .\gicg_actor\capi
   ```

3. 跑 perf smoke(N=4 baseline + N=16 stress):
   ```powershell
   .venv\Scripts\python -m pytest training\core\actor\tests\test_go_actor_perf_smoke.py -m smoke_full -v -s
   # N=16 version: 改 test 内 N_ACTORS = 16 + RUN_SECONDS = 30,然后跑同命令
   ```

4. 期望输出:fps_per_actor ≥ 4.4(N=16 fps≥70 gate),decode_errors=0,mem delta < 1 GB

## Phase 1.5-R — 闸门收尾重规划(2026-05-22)

P1.3/P1.4 标 DONE 但 verify 全程用 stub forward callback(`build_stub_zero_forward`)
绕过 production decode + 真 `DMCNetwork`;Win stress 一上真网络即暴露 socket forward
路径从未端到端跑通。 Phase 2(P2.X 5 commit + AZ/PPO scaffold)在 [blocker] 未关时
已启动 = 建在未验证地基。 本节倒回去用真网络真实关闭 Phase 1.5 闸门,关上前 Phase 2 冻结。

### Track A(顺序硬链)

- [ ] T-R1 合并 worktree A(`agent-a8e0dfbe540cb094e`)→ branch:`build_engine.py` 加
      `go build -a`(修 cgo `//export` cache stale)+ `dmc/_socket_decoder.py` 用
      `DMCInferenceNet` wrap 真 `DMCNetwork`(修 socket forward NotImplementedError)+
      配套 tests。 附:同步 `mp_factories.py:122` 注释 blake2b→sha256 +
      `test_dmc_mp_factories.py:132` 改 sha256(审计发现的注释/测试 stale)
- [ ] T-R2 删 Mac perf smoke 的 stub bypass — `test_go_actor_perf_smoke.py` 的
      `socket_forward_builder_path` 指向真 `build_dmc_socket_forward_callback` + 真
      `DMCNetwork`,Mac 重跑确认 production decode→forward 端到端真通(依赖 T-R1)
- [ ] T-R3 Win N=16 真网络 stress(走 `tools.runs.*` CLI sync+build+train),收
      fps/mem/decode_errors,真数据关 T-1.23 [blocker](依赖 T-R2 PASS)[blocker]
- [ ] T-R4 收尾标注(依赖 T-R3):P1.3/P1.4 DONE 降级标注 "stub-verified, re-closed
      by T-R2";P2.X 5 commit 标 "premature, pending re-verify";CFR/BC(T-2.5/T-2.6)
      按 D10 移出 I29 scope

### Track B(独立,可与 Track A 全程并行)

- [ ] T-R4-guard AZ/PPO `make_collector` 加 guard:`cfg.pipeline.actor_backend=='go'`
      时显式 raise(非静默忽略),提示 "I29 Phase 2 pending"。 + backlog.md I28 行被
      I29 commit 顺手改的注记一笔(审计发现)

## Phase 2 — per-paradigm adapter port(~300 LOC + per-paradigm)

- [ ] T-2.1 `openspec/specs/training-architecture/actor-backend.md` 落地 `ActorBackend` Protocol 规约
- [ ] T-2.2 `gicg_actor/az/obs_encoder.go` + `gicg_actor/az/opp.go`(MCTS PUCT)+ winrate gate test
- [ ] T-2.3 AZ collector 接 `GoActorBackend`,smoke + smoke_full PASS
- [ ] T-2.4 `gicg_actor/ppo/obs_encoder.go` + `gicg_actor/ppo/opp.go` + tests + PPO collector 接
- [ ] T-2.5 `gicg_actor/cfr/obs_encoder.go` + `gicg_actor/cfr/opp.go` + tests + CFR collector 接
- [ ] T-2.6 `gicg_actor/bc/obs_encoder.go`(BC 是 dataset-driven 无 opp,wrap dataset iterator)+
      BC adapter + tests + BC collector 接
- [ ] T-2.7 Phase 2 verify:5 paradigm smoke + smoke_full 全 PASS,Win 实测每 paradigm 跑通 [blocker]

## Phase 3 — production train + archive

- [ ] T-3.1 跑 stage3_b_v_legacy.toml 整局 1M frames train(N=64 actor stress test,生产 cfg 不动)
- [ ] T-3.2 metrics.jsonl 收 fps / mem / inf_server / gpu / cpu 全量,对照 Python baseline 数据 dump
- [ ] T-3.3 Mac gauntlet eval ckpt 收敛验证:wp vs F1-D2 落 Python baseline 95% CI 内(不只看 fps,
      要 RL signal 一致)
- [ ] T-3.4 docs 更新:
      - `training/paradigms/dmc/notes.md` 加 Phase 3.7 数据 + I29 ship 节
      - `docs/3_plans/backlog.md` I29 标 done + link archive
      - 关闭 backlog 中 N=16 / N=24 上限相关 item
- [ ] T-3.5 `/opsx:archive i29-go-actor-pool` archive change
