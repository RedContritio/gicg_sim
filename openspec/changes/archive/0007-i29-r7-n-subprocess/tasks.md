# Tasks — I29 R7 N independent Go subprocess

**Status:** All shipped (2026-05-25 session 4)

## R7.1 — 删 SHM inference path 全套 (commit `ff50548`,-1096 LOC)

- [x] T-7.1.1 删 `gicg_actor/inference_shm_client.go` + test (-526 LOC)
- [x] T-7.1.2 删 `training/core/actor/inference_server_shm_bridge.py` (-262 LOC)
- [x] T-7.1.3 `gicg_actor/pool.go` Config 删 SHM 字段 (`InferenceShmMode` / `SHMReqRingName` / `SHMRespRingNames` / `SHMReqCapacity` / `SHMReqSlotSize` / `SHMRespSlotSize`)
- [x] T-7.1.4 `cmd/gicg_actor/main.go`:删 SHM 分支 + `buildShmInferenceClients` + `parseConfig` SHM validation + `toPkgConfig` SHM 透传
- [x] T-7.1.5 `inference_server.py`:删 `shm_inference_cfg` 参数 + `InferenceShmBridge` import + spawn 分支
- [x] T-7.1.6 `go_subprocess_pipeline.py`:删 `inference_mode='shm'` 分支 + SHM kwargs + `PipelineHandle.inference_mode` 字段
- [x] T-7.1.7 `go_subprocess_collector.py`:删 inference_mode ctor param + 透传
- [x] T-7.1.8 `training/core/config/base.py PipelineCfg.inference_mode` field 删 + docstring update
- [x] T-7.1.9 `paradigm.py:_make_go_collector`:删 inference_mode 透传
- [x] T-7.1.10 `configs/dmc/bench_v_legacy_go.toml`:删 `inference_mode = "shm"` 行
- [x] T-7.1.11 `test_go_subprocess_5ep_e2e.py`:删 `[shm]` parametrize variant
- [x] T-7.1.12 Verify:`go build` clean,`go test` 6/6 packages PASS,`pytest -m smoke training/tests/` 5/5 PASS,DMC subprocess e2e 4/4 PASS,`test_dmc_async_collector` 13/13 PASS,ruff + gofmt clean

## R7.2 — spawn N independent Go subprocess (commit `0036241`,+161 / -57 LOC)

- [x] T-7.2.1 `gicg_actor/pool.go`:Config 加 `BaseActorID int` 字段 (>= 0 validation,subprocess[i] BaseActorID=i 确保 cross-subprocess unique clientID),`runInternal` goroutine spawn 内 actorID = BaseActorID + i (与 sinkFor(i)/infFor(i) local idx 解耦)
- [x] T-7.2.2 `cmd/gicg_actor/main.go`:Config 加 `BaseActorID int json:"base_actor_id,omitempty"` + parseConfig `>= 0` validation,`toPkgConfig` 透传到 `gicg_actor.Config.BaseActorID`
- [x] T-7.2.3 `training/core/actor/go_subprocess_pipeline.py`:
  - `PipelineHandle.go_proc` (single) → `go_procs: list[GoSubprocessHandle]` (N) with `n_actors` property accessor
  - `spawn_pipeline` 改 spawn N Go subprocess sequentially (each `n_actors=1` + `base_actor_id=i`) attached to shared SHM ring
  - `shutdown`:N parallel SIGTERM + sequential wait join + shared SHM close + InfServer stop
  - partial-spawn cleanup loop on spawn exception path
- [x] T-7.2.4 `training/paradigms/dmc/tests/test_go_subprocess_1ep_smoke.py`:`handle.go_proc` → `handle.go_procs[0]` (1ep_smoke n_actors=1 时单 handle)
- [x] T-7.2.5 不需改:`go_subprocess_collector.py` (PipelineHandle opaque)、`cmd/gicg_actor` actor wiring (NActors=1 trivially supported)、`gicg_actor/dmc/paradigm.go` (uses passed-in actorID)、`inference_server.py` (socket_clients=N 已 support)
- [x] T-7.2.6 Verify:`go build` clean,`go test` 6/6 packages PASS,`pytest -m smoke` 5/5 PASS,DMC subprocess e2e 6/6 PASS,`test_dmc_async_collector` 13/13 PASS,`smoke_full perf_smoke` N=4 fps/actor=4.62

## R7.3 — Mac fair bench verify (commit `fefe945` + `a4da6d1`)

- [x] T-7.3.1 3-seed initial run (`post_r7_2_fair.md`):Go/Py = 1.64x,Go variance CV 110%
- [x] T-7.3.2 5-seed extended run (`post_r7_2_fair_5seed.md`):Go/Py = **1.54x robust mean**,Go CV 67% / Py CV 30%
- [x] T-7.3.3 PR draft 更新 (`docs/superpowers/specs/2026-05-25-i29-redesign-pr-draft.md`):Status 改 "✅ ACCEPTANCE MET",Layer 4 加 post-R7.2 数据,Final acceptance summary 改 1.54x

## R7.4 — spec subtopic (本 change archive 同 batch ship)

- [x] T-7.4.1 新建 `openspec/specs/training-architecture/actor-backend.md` SHALL 子规约 (AB1-AB12 覆盖 actor_backend dispatch / N+2 topology / 0 cgo invariant / TCP-only inference / atomic spawn-shutdown)
- [x] T-7.4.2 `spec.md` §5 Subtopics 索引加 actor-backend 链接
