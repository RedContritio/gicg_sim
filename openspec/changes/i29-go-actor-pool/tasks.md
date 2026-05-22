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

- [x] T-R1 合并 worktree A → `build_engine.py` 加 `go build -a` + `_socket_decoder.py`
      用 `DMCInferenceNet` wrap 真 `DMCNetwork`(`84ed588`)
- [x] T-R2 删 Mac perf smoke stub bypass — 真 `DMCNetwork` 端到端(`eda9ea5`)
- [~] T-R3 Win N=16 真网络 stress —— **已跑,whack-a-mole 出 7 个结构性问题**(6 已修+提交:
      `7d41c82 cd20ab6 d347aff d4535e7 9d86635 fba68a1`)。 #7 producer-consumer 无界堆
      未解。 → T-1.23 [blocker] **未关**,转 Phase 1.5-R2 系统性收尾
- [ ] T-R4 收尾标注 —— 见 Phase 1.5-R2 T-RR.9

### Track B(独立,可与 Track A 全程并行)

- [x] T-R4-guard AZ/PPO `make_collector` guard `actor_backend=='go'` 显式 raise(`f2d3ece`)

## Phase 1.5-R2 — 管线穷举审计修复(2026-05-23)

T-R3 暴露 Go-actor → driver 管线结构性不完整。 全管线穷举审计(我审 + 独立 reviewer 复核 +
关键 claim 亲验)→ design.md D8。 3 个耦合修复簇 + 独立修复。 task 边界 = 提交就绪。

闸门 T-1.23 要 fps≥70 且 mem≤2GB **同时成立** —— 簇 1 保 mem,簇 2 保 fps,缺一不可。

### 簇 3 — episode 终结契约(先做:小、独立、修正确性 bug + 减泄漏)

- [x] T-RR.1 `paradigm.go` episode loop 退出后统一推 terminal marker(`Done=true`,
      `NLegal=0`)—— 覆盖 opp-final-blow / 截断 / me-final-blow 全路径(旧逻辑仅
      me-final-blow 置 done,~半数 episode 漏 → assembler 永不 finalize)。 marker 走
      `n_legal==0` 路径,assembler/wire 无需改。 Go integration test + assembler 契约测试

### 簇 1 — backpressure + 队列有界化(RSS 10.5GB 机制)

- [x] T-RR.2 `_buffers` 在途上限 —— LRU OrderedDict,超限驱逐「最久未活跃」episode
      (orphaned:actor 死亡 / conn reset 后永不 done)。 ingest 时 `move_to_end` 使活跃
      episode 不被误杀。 `collect 不丢弃` 因与 `_ready` 有界化耦合(单独做会把无界增长
      从 `_buffers` 搬到 `_ready`),并入 T-RR.3。 assembler LRU 驱逐测试
- [x] T-RR.3 backpressure 端到端 + collect 不丢弃:listener `sink_callback` 改 `_enqueue`
      推有界 `queue.Queue(maxsize)`;`collect()` 调 `_drain_queue_assemble` 从 queue
      **lazy-ingest** —— 只取够 `n_episodes` 的 transition,余下留 queue(queue 即唯一
      backlog 蓄水池,满 → listener 阻塞 put → socket 回压 → Go 限流;`_capture_obs_np`
      重组装随 ingest 移到 driver 线程,不再饿死 listener)。 lazy-ingest 天然不 over-drain
      → 无 leftover-丢弃问题。 **#12**:Go `TransitionWriter` 5min 写超时(回压阻塞不触发)
      + `Push` 失败中止 episode 不致死 actor。 `close()` 重排(先 set listener stop →
      `_enqueue` 丢弃 → 解 socket 回压)。 collector 全栈(close 无 hang / 真 backpressure)
      走 T-RR.9 Win stress 验证

### 簇 2 — inference 真 batching(0.4 eps/s 主因,fps 闸门关键路径)

- [ ] T-RR.4 InfServer socket listener 接 `request_q` batching + per-conn response
      路由(完成 docstring deferred 的 P1.3c)。 socket 协议加 `req_id`。 配 batching test
- [ ] T-RR.5 Go 端 inference 并发:去 `inference_client.go` 单 conn mutex —— per-actor
      `InferenceClient` conn,或走 T-RR.4 的 `req_id` 乱序应答。 依赖 T-RR.4

### 独立修复(可并行,不阻塞主链)

- [ ] T-RR.6 静默路径改 fail-loud:`_socket_decoder.py`/`_go_assembler.py` reshape size
      mismatch 改 raise;`pickActionEpsilonGreedy` logits-nLegal 不一致改 raise;listener
      bind 失败不再静默 set `ready_event`
- [ ] T-RR.7 actor 死亡可见性:`pool.go` actor goroutine fatal 上报(alive count 经
      C API 暴露);perf smoke 加"结束时 N actor 全活"断言
- [ ] T-RR.8 wire header struct version/size 运行时交叉校验(transition + infer 两路)

### 收尾

- [ ] T-RR.9 Win N=16 真网络 stress 重跑,关 T-1.23 [blocker]:fps≥70 + mem≤2GB +
      decode_errors=0 + 结束 16 actor 全活。 依赖 T-RR.1/.3/.5。 + 收尾标注(P1.3/P1.4
      "stub-verified, re-closed";P2.X "premature";CFR/BC 移出 scope)[blocker]

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
