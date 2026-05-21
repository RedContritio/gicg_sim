# Tasks — I29 Go actor pool

4 phase 顺序 ship。 每 phase 末 verify gate 通过才进下一 phase(标 `[blocker]`)。 边界硬约束:
**`gicg_engine/` 零侵入**,所有 RL 代码进新顶层 `gicg_actor/`。

## Phase 0 — scaffold(~250 LOC)

- [ ] T-0.1 创建顶层 `gicg_actor/` package(跟 `gicg_engine/` 并列)+ 空 `pool.go`(单 goroutine
      spawn / stop API)
- [ ] T-0.2 `gicg_actor/capi/main.go` + 最小 C API:
      ```
      int gicg_actor_hello(void);          // return 0 on success
      int gicg_actor_start_pool(int n);
      int gicg_actor_stop_pool(void);
      ```
- [ ] T-0.3 build 命令验证(Mac):
      ```
      go build -buildmode=c-shared -o gicg_env/libgicg_actor.dylib ./gicg_actor/capi
      ```
      Win PowerShell 同模板(`-o gicg_env/libgicg_actor.dll`)
- [ ] T-0.4 SIGTERM handler:`gicg_actor/pool.go` init 装 `signal.Notify(c, syscall.SIGTERM); go func(){ <-c; os.Exit(0) }()`
      no-op handler(防 cgo + Python multiprocessing 信号互锁,memory:
      feedback_go_cgo_signal_handler)
- [ ] T-0.5 `training/core/actor/go_backend.py` ctypes wrapper minimal:
      `GoActorBackend.start(n)` + `.stop()`,内部 `ctypes.CDLL('libgicg_actor.dll')`
- [ ] T-0.6 atexit hook:Python `GoActorBackend.__init__` register `atexit.register(self.stop)` 兜
      process exit cleanup
- [ ] T-0.7 hello-world test:`pytest training/core/actor/tests/test_go_backend_hello.py`:
      - Python load lib → call `gicg_actor_hello()` 返 0
      - Python call `gicg_actor_start_pool(1)` → assert goroutine print "ok" (via Go stdout) →
        call `gicg_actor_stop_pool()` → assert goroutine join 干净 < 2s
      - 跑 100 次连续不 hang(防 SIGTERM handler missing 时 mp 关闭挂死)
- [ ] T-0.8 `libgicg` 不受影响 smoke:跑 `pytest gicg_env/tests/` 全 PASS(现 Python ctypes call
      libgicg 无 regression — engine 零侵入验证)
- [ ] T-0.9 跨平台 build CI:Mac + Win build 各跑过(无 Linux box,Linux 留 P3)
- [ ] T-0.10 Phase 0 verify:hello-world ×100 Mac+Win 不 hang + libgicg 现 Python tests 全 PASS [blocker]

## Phase 1 — production e2e(~2200 LOC,一坨上)

注:本 phase 是单大 PR,内部按 T-1.X 顺序 develop + 合并前 verify。 risk 高(2000+ LOC 一次性 ship),
但 user 明确不接受 mock 中间态。

### P1.1 Go actor 主体(paradigm-agnostic,~800 LOC)

- [ ] T-1.1 `gicg_actor/pool.go`:N goroutine 调度,共享 engine pool,生命周期 start/stop
- [ ] T-1.2 `gicg_actor/episode.go`:episode 主 loop,调 `engine.Step()` / `Clone()` / 接 paradigm
      adapter 拿 obs + 提交 inference + 处理 transition
- [ ] T-1.3 `gicg_actor/adapter.go`:`ObsEncoder` + `OppBaseline` interface + paradigm 注册表
- [ ] T-1.4 `gicg_actor/inference_client.go`:TCP localhost socket 客户端,raw bytes wire format
      (D5 schema)
- [ ] T-1.5 `gicg_actor/shm_ring.go`:transition SHM writer,mirror `training/core/actor/shm_ring.py`
      协议(cross-platform mmap)
- [ ] T-1.6 `gicg_actor/{pool,episode,adapter,inference_client,shm_ring}_test.go`:Go unit tests
      (单 goroutine episode + socket roundtrip mock + SHM round-trip)

### P1.2 DMC paradigm adapter(~600 LOC)

- [ ] T-1.7 `gicg_actor/dmc/obs_encoder.go`:port `_capture_obs_np` + `_encode_static_np` 到 Go,
      接 engine state,返 numpy-equivalent `[]float32` + `[]int64`(refs/pay)
- [ ] T-1.8 `gicg_actor/dmc/obs_encoder_test.go`:**bit-exact** 数值等价测 — 10k random observation,
      Go bytes == Python `_capture_obs_np` bytes byte-equal 比对
- [ ] T-1.9 `gicg_actor/dmc/greedy_player.go`:port `greedy_player.select_action` +
      `_score_best_response` 完整逻辑(F1-D2 + F1-D4 + dice scheduling)
- [ ] T-1.10 `gicg_actor/dmc/greedy_player_winrate_test.go`:**winrate gate** —
      - Go-D2 vs random n=128 swap,winrate 落 Python-D2 vs random baseline 95% CI 内
      - Go-D4 vs Python-D2 n=128 swap,winrate 落 Python-D4 vs Python-D2 baseline 95% CI 内
- [ ] T-1.11 `gicg_actor/dmc/` 注册 DMC adapter 到 `gicg_actor.adapter` 注册表

### P1.3 InfServer accept Go socket(~150 LOC Python)

- [ ] T-1.12 `training/core/actor/inference_server.py` 加可选 socket listener(`mp.Queue` 路径保留):
      cfg flag 或 `accept_socket=True` 参数,listener thread accept Go connections,read raw bytes →
      decode header → batched_forward → write response raw bytes
- [ ] T-1.13 InfServer socket protocol 单测:Python client mock 发 raw bytes 请求,assert decoded
      obs_dict + response bytes 正确

### P1.4 Python backend wiring(~300 LOC Python)

- [ ] T-1.14 `training/core/actor/backend.py`:`ActorBackend` Protocol(start / pull_transitions /
      push_weights / stop)
- [ ] T-1.15 `training/core/actor/python_backend.py`:重构现 `actor_process.actor_main` 包成
      `PythonActorBackend` impl,protocol-compatible(向后兼容 5 paradigm)
- [ ] T-1.16 `training/core/actor/go_backend.py`:完整 `GoActorBackend` 实现 — ctypes wrapper +
      SHM reader + InfServer socket 配置传递给 Go side
- [ ] T-1.17 DMC collector(`training/paradigms/dmc/collector.py`)接 `ActorBackend` — cfg flag
      `pipeline.actor_backend: 'python' | 'go'` 切换
- [ ] T-1.18 schema 加 `pipeline.actor_backend` 字段(`training/core/config/schema.py`)+ 测

### P1.5 Win 实测 verify

- [ ] T-1.19 sync 当前 branch 到 Win,build `libgicg_actor.dll` + `libgicg.dll` (后者 ensure
      no regression)
- [ ] T-1.20 跑 `tools.runs.train stage3_b_v_legacy.toml --override pipeline.actor_backend=go --override paradigm.dmc.total_frames=10000`,
      ~5 min,assert pipeline 跑通 + metrics.jsonl 含 kind=iter / inf_server / mem / cpu / gpu 全行
- [ ] T-1.21 fps 实测对照:N=16 Go backend fps 应 ≥ 70(对照 Python baseline 35,2x 是 gate);若 <70
      report 实际数据 + 审视瓶颈是否转 InfServer 上限或别处
- [ ] T-1.22 mem 实测对照:N=16 master RSS Go ≤ 2 GB(对照 Python 11.4 GB);InfServer process mem
      ≤ baseline(< 10 GB)
- [ ] T-1.23 Phase 1 verify:obs bit-exact + opp winrate gate + N=16 Win fps ≥ 70 + mem ≤ 2 GB 全过
      [blocker]

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
