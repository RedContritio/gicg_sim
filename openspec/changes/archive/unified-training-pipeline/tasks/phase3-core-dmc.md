---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../tasks.md
---

# Phase 3 — core scaffold + DMC async 迁移

> First migration:把 `training/dmc/` + 部分 `training/framework/` 内容
> 抽进 `training/core/`,通过 6 protocol 重新接入。完成后 DMC smoke 通过
> 新管线,F1-D2 win rate ≥ baseline - 0.02。

## 1. 总 LOC 估 / Wall

- **LOC 估**:~3000 new(core/ 模块)+ ~500 modified(dmc adapter)
- **Wall 估**:~2 weeks(主路径);P3.5 G1 Go 化并行
- **Smoke 门槛**:DMC 100k transitions on new pipeline,F1-D2 win rate ≥
  baseline(`artifacts/202605..._s_dmc_baseline`)- 0.02

## 2. 任务清单

### P3-T1 Core protocols ship(基础)

- [x] **P3-T1.1**:`training/core/protocols.py` 写 6 protocol 定义
  (Paradigm / Collector / Buffer / LossComputer / EpisodePolicy /
  NetworkProvider)+ TypedDict for `Transition` / `TrainBatch` / `EpisodeRecord`
  / `LossResult` / `StepPlan` / `PipelineState`(~250 LOC)
- [x] **P3-T1.2**:`training/core/__init__.py` export 6 protocol(~20 LOC)
- [x] **P3-T1.3**:`training/core/checkpoint.py` 协议 + load/save 实现(~250
  LOC,整合 az/checkpoint + dmc 等价物)
- [x] **P3-T1.4**:`training/core/logging.py` MetricsLogger(metrics.jsonl
  + TB)(~200 LOC)
- [x] **P3-T1.5**:pytest cover 全 protocol typing + checkpoint roundtrip
  (~150 LOC tests)

依赖:无;blocked by:P2 ship

### P3-T2 Core config layer

- [x] **P3-T2.1**:`training/core/config/base.py` TrainingConfig + nested
  dataclass(~200 LOC)
- [x] **P3-T2.2**:`training/core/config/loader.py` TOML + extends chain
  resolver(~250 LOC)
- [x] **P3-T2.3**:`training/core/config/inheritance.py` `INHERITED_FIELDS`
  registry + resolver + `derive_seed`(~150 LOC)
- [x] **P3-T2.4**:`training/core/config/schema.py` R1-R7 placement schema
  validator(~200 LOC)
- [x] **P3-T2.5**:pytest cover R1-R7 全部 + 继承 chain(~250 LOC tests)

依赖:P3-T1.1

### P3-T3 Core network layer

- [x] **P3-T3.1**:`training/core/network/encoder.py` 抽 framework/network
  共享 encoder(~250 LOC)
- [x] **P3-T3.2**:`training/core/network/heads.py` PolicyHead / ValueHead /
  QHead / AvgPolicyHead(~150 LOC)
- [x] **P3-T3.3**:`training/core/network/actor_critic.py` 通用组装 + paradigm
  head dispatch(~150 LOC)
- [x] **P3-T3.4**:`training/core/network/struct_readout.py` 抽 az c1v7 实现
  (~150 LOC)
- [x] **P3-T3.5**:`training/core/network/hook_emb.py` 抽 hook attn(~200
  LOC,from framework/network/hook_attn.py)
- [x] **P3-T3.6**:pytest cover encoder + heads + actor_critic(~200 LOC tests)

依赖:P3-T1.1

### P3-T4 Core buffer layer

- [x] **P3-T4.1**:`training/core/buffer/base.py` Buffer base 接口(~80 LOC)
- [x] **P3-T4.2**:`training/core/buffer/replay.py` 通用 replay(~200 LOC)
- [x] **P3-T4.3**:`training/core/buffer/static_dedup.py` from framework(~120
  LOC)
- [x] **P3-T4.4**:`training/core/buffer/shared.py` SHMRingBuffer(~300 LOC,
  from dmc/shared_buffer.py 抽)
- [x] **P3-T4.5**:pytest cover buffer 并发 push / sample(~200 LOC tests)

依赖:P3-T1.1

### P3-T5 Core actor / inference 层

- [x] **P3-T5.1**:`training/core/actor/episode_runner.py` EpisodeRunner +
  EpisodeSpec(~150 LOC)
- [x] **P3-T5.2**:`training/core/actor/policy.py` EpisodePolicy 基类(~80 LOC)
- [x] **P3-T5.3**:`training/core/actor/network_provider.py` Local + Remote
  Provider(~250 LOC)
- [x] **P3-T5.4**:`training/core/actor/provider_factory.py`(~80 LOC)
- [x] **P3-T5.5**:`training/core/actor/weights_shm.py` Weights SHM 协议
  (~250 LOC,from framework/inference/weights_*.py)
- [x] **P3-T5.6**:`training/core/actor/weights_watcher.py`(~120 LOC)
- [x] **P3-T5.7**:`training/core/actor/inference_server.py` from framework
  (~300 LOC)
- [x] **P3-T5.8**:`training/core/actor/inference_client.py`(~200 LOC)
- [x] **P3-T5.9**:`training/core/actor/actor_process.py` 通用 actor main
  (~200 LOC,from dmc/_actor.py 抽)
- [x] **P3-T5.10**:`training/core/actor/runtime.py` 进程编排(~250 LOC)
- [x] **P3-T5.11**:`training/core/actor/ipc/` SHM ring + queue + sync(~300
  LOC)
- [x] **P3-T5.12**:pytest cover EpisodeRunner + Provider local/remote(~300
  LOC tests)

依赖:P3-T1.1 / P3-T3.x / P3-T4.x

### P3-T6 Core eval / opponent 层

- [x] **P3-T6.1**:`training/core/eval/server.py` EvalServer(~250 LOC)
- [x] **P3-T6.2**:`training/core/eval/worker.py` EvalWorker(~200 LOC)
- [x] **P3-T6.3**:`training/core/eval/periodic.py` PeriodicScheduler(~120 LOC)
- [x] **P3-T6.4**:`training/core/eval/job.py` EvalJob + EvalReport(~80 LOC)
- [x] **P3-T6.5**:`training/core/eval/scenario.py` ScenarioFactory(~150 LOC)
- [x] **P3-T6.6**:`training/core/eval/baselines.py` OpponentRegistry baselines(~200 LOC)
- [x] **P3-T6.7**:`training/core/eval/statistics.py` from framework(~120 LOC)
- [x] **P3-T6.8**:`training/core/eval/matchup.py` from framework(~200 LOC)
- [x] **P3-T6.9**:`training/core/opponent/pool.py` OpponentRegistry +
  `training/core/opponent/mix.py`(~250 LOC)
- [x] **P3-T6.10**:pytest cover eval scheduler + worker + opponent(~250
  LOC tests)

依赖:P3-T5.x

### P3-T7 Pipeline driver

- [x] **P3-T7.1**:`training/core/pipeline.py` 主 driver loop(~200 LOC)
- [x] **P3-T7.2**:`training/core/env_factory.py` paradigm-agnostic(~100
  LOC,from az/env_factory.py)
- [x] **P3-T7.3**:`training/core/scenario_factory.py`(~80 LOC)
- [x] **P3-T7.4**:`training/core/obs_constants.py` from framework(~150 LOC)
- [x] **P3-T7.5**:`training/core/step_encoding.py` from framework(~200 LOC)
- [x] **P3-T7.6**:`training/core/nan_guard.py` from dmc(~80 LOC)
- [x] **P3-T7.7**:pytest cover driver smoke(synthetic paradigm)(~250 LOC tests)

依赖:P3-T1-T6

### P3-T8 DMC paradigm adapter

- [x] **P3-T8.1**:`training/paradigms/dmc/paradigm.py` DMCParadigm 实现 6
  protocol 接入(~300 LOC)
- [x] **P3-T8.2**:`training/paradigms/dmc/config.py` DMCParadigmConfig(~80 LOC)
- [x] **P3-T8.3**:`training/paradigms/dmc/collector.py` MultiProcessActorCollector
  (~200 LOC,wrap core actor_process)
- [x] **P3-T8.4**:`training/paradigms/dmc/loss.py` DMCLoss(logit-as-Q)
  (~150 LOC)
- [x] **P3-T8.5**:`training/paradigms/dmc/policy.py` EpsilonGreedyPolicy
  (~120 LOC)
- [x] **P3-T8.6**:`training/paradigms/dmc/network.py` head 组装(~80 LOC)
- [x] **P3-T8.7**:pytest cover DMC paradigm 集成(~200 LOC tests)

依赖:P3-T7

### P3-T9 `tools/run.py` 单入口

- [x] **P3-T9.1**:`tools/run.py` paradigm dispatch + cfg validate + run_pipeline
  call(~200 LOC)
- [x] **P3-T9.2**:cfg migrator `tools/_meta/migrate_cfg.py`(旧 cfg → 新
  cfg 自动补字段)(~200 LOC)
- [x] **P3-T9.3**:pytest cover `tools/run.py` 通过 cfg dry-run(~150 LOC tests)

依赖:P3-T2 / P3-T7 / P3-T8

### P3-T10 DMC smoke + baseline 对照

- [x] **P3-T10.1**:跑 baseline `artifacts/202605..._s_dmc_baseline`(P2 ship
  时记录),50k transitions(~6h)
- [x] **P3-T10.2**:跑 new pipeline smoke `configs/dmc/v_phase2_smoke.toml`,
  同 cfg + 同 seed(~6h)
- [x] **P3-T10.3**:对比 episodes/s / loss curve / F1-D2 win rate,门槛 ±
  baseline tolerance
- [x] **P3-T10.4**:若不通过 → root cause analysis + 修复 + 重跑

依赖:P3-T9

### P3-T11 全 pytest + 全 cfg validate

- [x] **P3-T11.1**:`.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/`
  全 pass
- [x] **P3-T11.2**:全 configs/**/*.toml `python -m tools.run --dry-run` 通过
- [x] **P3-T11.3**:ruff format + gofmt 通过
- [x] **P3-T11.4**:check_line_limits + check_openspec_indices 通过

依赖:P3-T10

## 3. 总 P3 ship 门槛

P3-T1-T11 全 done + DMC smoke 通过 + 全 pytest pass → P3 ship。
进入 P4(其他 paradigm 接入)。

## 4. Cross-references

- 主 design → [`../design.md`](../design.md)
- Migration plan → [`../design/migrations.md`](../design/migrations.md)
- Risks(R-A DMC regression)→ [`../design/risks.md`](../design/risks.md) §1
- P3.5 并行 plan(F1-Dn Go 化)→ 后续 follow-up change
