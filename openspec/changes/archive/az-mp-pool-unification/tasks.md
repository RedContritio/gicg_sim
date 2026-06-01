---
last_updated: 2026-06-01
status: DRAFT
schema_version: 0
change_id: az-mp-pool-unification
---

# Tasks — AZ mp pool unification

> 单 session subagent-driven implementation。Phase 1 propose;Phase 2 implement
> (T0 已 done propose,T1-T8 implement);Phase 3 verify。

## Phase 1 — Propose

- [x] **T0**:propose commit — 4 artifact
  - `proposal.md` (本 change why/what/scope + D1-D5 推荐 summary)
  - `design.md` (5 决策点详 + arena audit 结果 + risk list)
  - `tasks.md` (本文件)
  - `specs/training-architecture/spec.md` (placeholder per D4 推荐 A — no
    spec change required)
  - **LOC**:~1500 artifact only
  - **依赖**:无

## Phase 2 — Implementation

> **方向演进**(读 design.md §2.2-CORRECTION + §2.3-CORRECTION-2):
> - **D1 → B'** (2026-05-29 T1 forensic):actor 经 AB14 `episode_runner_factory`
>   插 `AZSelfPlayRunner` 包裹现有 `play_self_game`(非 EpisodeRunner),与 CFR
>   traversal-runner 同构。T1/T2/T2a 按 B' done。
> - **→ 方向 C** (2026-06-01 T4 dead-stack 审计):production `tools.runs.train`
>   完全走统一 pipeline `make_collector` → `AZAsyncCollector`(async,T1/T2 ship)/
>   `AZSelfPlayCollector`(serial),**不经过 legacy 栈**。`train_az → run_async →
>   ParallelInferencePool` 是独立 dead 栈。原 T3-T8「改 run_async 接 collector」
>   前提失效(改 dead 入口无意义)。**改为废 legacy 全删**(下方 T3-T8 重规划)。
>   user scope 决定(3 问):serial verify + async follow-up / profiling 迁统一入口 /
>   config 一并全删 + 全迁移。

- [x] **T1** (B'):新建 `training/paradigms/az/mp_factories.py`
  - **commit**:`7269e22`
  - 5 件套(build_env_factory / opp_registry stub / policy stub /
    build_az_selfplay_runner[AB14 `AZSelfPlayRunner` 包 `play_self_game`] /
    spec_sampler) + `_AZRemoteProvider`(eval_state / game_start / observe_env /
    update_weights / close,走 `InferenceClient.request` 路由 server-side
    `handle_eval_batch`)。
  - **依赖**:T0

- [x] **T2** (B'):重写 `AZAsyncCollector` 接 InferenceServer + 拆 `_async.py`
  - **commit**:`39ea6b8`
  - weights 走 `InferenceServer.push_weights`(server 持权重),AZ 不用 WeightsSHM
    (`_AZRemoteProvider.update_weights` no-op version read);actor_kwargs 加
    `episode_runner_factory_path=build_az_selfplay_runner` + `push_episode_record
    =True`;collect 读 `_AZRunnerOutput.selfplay_result` → `(game_static, steps)`;
    300-line cap 拆分 `AZAsyncCollector` → 新 `_async.py`(collector.py 留 serial
    `AZSelfPlayCollector`);test 重写匹配新契约。
  - **依赖**:T1

- [x] **T2a** (SKIPPED — proxy,不改 core):`actors_alive_count()`
  - **commit**:`39ea6b8`
  - 不改 `core/actor/runtime.py`;`AZAsyncCollector` proxy
    `sum(ap.is_alive() for ap in runtime.actor_procs())`。
  - **依赖**:T2

---

> **以下 T3-T8 = 方向 C 重规划(2026-06-01,替换原 B' 删 inference_pool + 改
> async_loop 计划)**。删除/保留边界经 Explore dead-code 审计确定(详 design.md
> §2.3-CORRECTION-2)。每步先 grep 确认 dead 再删,单元测试过再下一步。

- [x] **T3** (commit `56797ff`):删 legacy mp 核心栈 + guard tests
  - **DELETE 文件**:
    - `training/paradigms/az/train_az.py`
    - `training/paradigms/az/train_loop/` 整个子包(`__init__.py` / `async_loop.py`
      [run_async] / `helpers.py` / `run_result.py` / `stats_ingest.py`)
    - `training/paradigms/az/inference_pool.py` + `inference_worker.py`
    - `training/paradigms/az/arena.py` (2026-06-01 纠正 — champion arena 随 legacy 退役)
    - `training/paradigms/az/config_loader.py` (2026-06-01 纠正 — import 被删 AZConfig)
    - `training/core/gauntlet.py` (2026-06-01 **连锁纠正,超原范围** — `dispatch_gauntlet`
      唯一非-test caller 是被删的 `train_loop/async_loop`;统一 pipeline 的 gauntlet eval
      走 eval_service `kind=gauntlet` matchup(未删),此 helper 仅服务 legacy async_loop,
      随之退役。删后 working tree 残留引用 0)
  - **DELETE guard tests**:`test_train_az.py` / `test_parallel_inference.py` /
    `test_parallel_pool_deadlock.py` / `test_az_champion_path.py` /
    `test_az_train_az_phase2_path.py` / `test_az_inference_phase2_path.py` /
    `test_az_config_train_loop_phase2_zeta.py` / `test_arena.py` /
    `test_az_arena_phase2_path.py` / `test_config_loader.py` /
    `test_gauntlet_path.py` (2026-06-01 **连锁纠正** — 实为 `dispatch_gauntlet` guard test,
    原 T5 误列为「迁移」;随 `core/gauntlet.py` 一并删除)
  - **改动**:`git rm`。`pool_spec.py` **不删**(SHARED — 只随 inference_worker
    没掉它的 caller)。`__init__.py`(az 包顶层)移除 `train_az` / `inference_pool` /
    `inference_worker` / `arena` / `config_loader` re-export 条目。删 config_loader
    前核查 `tools/eval/_paradigm.py` AZ reserved slot(not-implemented)不 break。
  - **注**:T3 删 `config_loader.py` 须早于 T4 删 `AZConfig`(config_loader import
    AZConfig,反序会留悬空 import)。
  - **LOC**:~ -900 (prod) + ~ -600 (test)
  - **依赖**:T2 (统一 pipeline async 已就绪,删 legacy 不影响 production)
  - **Risk**:删前 grep 确认 production 零 import(docstring/注释 残留 OK):
    ```bash
    grep -rn "import.*\(train_az\|inference_pool\|inference_worker\|train_loop\)" \
      training/ tools/ --include='*.py' | grep -v __pycache__ | grep -v "tests/"
    ```
    只允许 hit T4-T8 同步处理的文件(profile / debug / config)。

- [x] **T4** (commit `b8ae454`):`config.py` 部分删除 — 删 `AZConfig` + 3 presets
  - **File**:`training/paradigms/az/config.py`
  - **DELETE 符号**:`AZConfig` (class) + `smoke_config` / `fixed_1v1_config` /
    `random_1v1_config` + `__all__` 对应 4 条目 + 随之 unused imports
    (`TrainingConfig` / `InferenceServerConfig` / `AgentConfig` / `ObsConfig` /
    `ScenarioConfig` — 逐个 grep 确认文件内无其它引用再删)。
  - **KEEP**:`AZParadigmConfig` / `MCTSCfg` / `TrainStepCfg` / `AgentShapeCfg`
    (Phase-1 frozen dataclasses) + 它们需要的 imports。
  - **LOC**:~ -150
  - **依赖**:T3 (train_az/inference_pool/worker 的 AZConfig caller 已删)
  - **Risk**:审计标注 `MCTSConfig`/`TrainStepConfig` import 在删 AZConfig 后可能
    也变 unused — 删前 grep 确认 `MCTSCfg`/`TrainStepCfg` 是否仍引用它们。

- [x] **T5** (commit `68d9d4d`):迁移 5 production-adjacent test fixture
  - **File**:`test_eval_service_matchup.py` / `test_eval_service_schema.py` /
    `test_eval_service_errors.py` / `test_core_eval_baselines.py` /
    `test_scenario_sampling.py`
    (原列 6 个,`test_gauntlet_path.py` 改 T3 删除 — 见 T3 连锁纠正)
  - **改动**:这些 test 用 `smoke_config`/`fixed_1v1_config`/`random_1v1_config`
    当 agent-building fixture(非 legacy-stack test)。删 presets 后改用
    `AZParadigmConfig` 直构,或新建共享 fixture
    `training/tests/_fixtures/az_cfg.py`(若 ≥3 test 复用,DRY)。
    `test_scenario_sampling.py` 特别:用 `AZConfig`/`random_1v1_config` 仅为测
    `make_env_factory` + ScenarioConfig forwarding(production env_factory)→ 改直构
    `ScenarioConfig`/`AZParadigmConfig`。
  - **LOC**:~ +60 / -40 (fixture 迁移)
  - **依赖**:T4
  - **Risk**:eval/gauntlet test 跑真 eval_service(per `feedback_eval_service_precheck`)
    — 迁移后须真跑确认 fixture agent 构造等价(非 stub)。

- [x] **T6** (commit `3fc7790`):迁移 5 `tools/debug/*` 脚本
  - **File**:5 个 debug 脚本(grep `fixed_1v1_config`/`smoke_config` 定位)
  - **改动**:diagnostic 脚本改用 `AZParadigmConfig` / 统一 cfg 构造 agent。
    `watch_run.py` 仅 docstring 提及 train_az — 改注释即可,无 import 迁移。
  - **LOC**:~ +40 / -30
  - **依赖**:T4
  - **Risk**:debug 脚本无 test 覆盖 — 迁移后须 smoke 跑一遍(import + 单步)确认
    不 broken(per `feedback_tool_production_smoke_required`)。

- [x] **T7** (commit `e427b83`):迁移 2 profile 脚本到统一 pipeline 入口
  - **File**:`tools/profile/profile_parallel.py` + `tools/profile/profile_smoke.py`
  - **改动**:
    - `profile_parallel.py`:`smoke_config` + `train_az(cfg)` → `tools.runs.train`/
      `run_pipeline` + AZ cfg(`mode='async'` / `num_actors=4` 替 `n_workers=4` /
      `sync_interval_games` → `sync_weights_every_train_steps`-style cadence),
      包 `cProfile`。
    - `profile_smoke.py`:`fixed_1v1_config` + `train_az(cfg)` → serial
      `run_pipeline`(`mode='serial'` / num_actors=1 / arena+gauntlet disabled),
      `result.n_games_played`/`artifacts_dir` → pipeline run-dir + `PipelineState`。
  - **LOC**:~ +30 / -20
  - **依赖**:T4
  - **Risk**:profile 脚本是唯一非-test train_az production caller — 迁移后 smoke
    import + 单步跑确认 cProfile 仍 capture。

- [x] **T8** (commit `3b905f0`):改 `test_production_tests_az_refs_phase3{c,d}` allowlist
  - **File**:`test_production_tests_az_refs_phase3c.py` +
    `test_production_tests_az_refs_phase3d.py`
  - **改动**:删 allowlist 里指向已删 test 的 stale 条目 — phase3d 的
    `test_train_az.py` / `test_parallel_inference.py` /
    `test_parallel_pool_deadlock.py`;phase3c 的 `test_config_loader.py`
    (config_loader 已删,纠正后不再 KEEP)。grep 确认 allowlist 每条目对应文件
    存在(missing → FileNotFoundError/skip)。
  - **LOC**:~ -10
  - **依赖**:T3 (test 删后)

## Phase 3 — Verify

- [x] **T9** (DONE — 128 passed, 3 skipped):`pytest test_az_*` unit
  - **Command**:`.venv/bin/python -m pytest -n 4 training/tests/test_az*.py -q`
  - **Pass**:0 new failures vs baseline (迁移后 fixture 无 regress)
  - **依赖**:T5, T8

- [x] **T10** (DONE — 1 passed):`pytest -m smoke -k az` (serial 统一 pipeline 路径)
  - **Command**:`.venv/bin/python -m pytest -m smoke training/tests/ -q -k az`
  - **Pass**:AZ smoke 不 break
  - **依赖**:T9

- [x] **T11** (DONE — 0 code-path hit;残留仅 docstring + DMC 自有符号):grep legacy 删尽
  - **Command**:
    ```bash
    grep -rn "train_az\|run_async\|ParallelInferencePool\|inference_pool\|inference_worker\|train_loop\|AZConfig\|smoke_config\|fixed_1v1_config\|random_1v1_config" \
      training/ tools/ --include='*.py' | grep -v __pycache__ | grep -v "archive/"
    ```
  - **Pass**:0 import hit (仅 docstring/注释残留,human review 确认无 code path)
  - **依赖**:T3, T4, T5, T6, T7, T8

- [x] **T12** (DONE — eval_service 19 passed + scenario/baselines + profile_smoke serial 50 局 exit 0):迁移消费者全过 (eval / gauntlet / debug / profile)
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -n 4 training/tests/test_eval_service_*.py \
      training/tests/test_core_eval_baselines.py training/tests/test_gauntlet_path.py \
      training/tests/test_scenario_sampling.py -q
    .venv/bin/python -m tools.profile.profile_smoke   # smoke import + 单步
    ```
  - **Pass**:eval/gauntlet/scenario test PASS + profile 脚本 import + 单步无 error
  - **依赖**:T5, T6, T7

- [x] **T13** (DONE — 44 files clean, 删文件后无新 violator):`ruff format` + line limit hook
  - **Command**:
    ```bash
    .venv/bin/ruff format training/paradigms/az/ tools/profile/
    .venv/bin/python -m tools._meta.check_line_limits | grep -E "az" || echo "PASS"
    ```
  - **Pass**:format 0 changes + 删文件后无新 violator
  - **依赖**:T12

- [x] **T14** (DONE — check_openspec_indices PASS):openspec validate
  - **Command**:`.venv/bin/python -m tools._meta.check_openspec_indices`
  - **Pass**:索引完整 + spec delta 格式 OK
  - **依赖**:T0

## Follow-up (非本 change gate — 挂 pipeline-async-weight-sync change 之后)

- [x] **T15** (DONE 2026-06-01):AZ async e2e verify
  - **依赖**:`pipeline-async-weight-sync` change ship (weight-sync fix) — **已 7/8 ship**
  - **实现**:新 `training/tests/test_az_async_mp_e2e.py` (smoke_full):2-actor 真
    spawn + InferenceServer 起 + push 初始权重 + N=2 InferenceClient + AB14
    `build_az_selfplay_runner`(play_self_game)+ bounded-grace drain 真 selfplay
    trajectory + `sync_weights` bump `_weights_version`(server.push_weights)+
    state_dict 往返 + clean shutdown < 12s。**实跑 2× PASS(4.8s / 3.4s,均提前退出
    = 真 drain 到 ≥1 selfplay 局,非容忍 0)**。补上 `test_az_async_collector.py`
    docstring 承诺但从没建的 "T7 smoke_full suite"(CFR/PPO 有 async mp e2e,AZ 此前没)。
  - **意义**:统一 pipeline AZ async path(AZAsyncCollector)真-spawn **首次验证通过** —
    废 legacy AZ stack(方向 C T3-T8)的前置 gate 满足(替代品已证可跑,删 legacy 有底)。
  - **注**:此 e2e 在 collector 层验 spawn+selfplay+sync_weights;run_pipeline async
    整链组合(driver→sync_weights→actor)由 pipeline T4 driver-integration e2e(
    paradigm-agnostic)+ 本 AZ collector e2e 复合覆盖。真 production 长跑 = T7
    run-149(GPU box)。

## 总进度

- Phase 1:1/1 (T0)
- Phase 2:8/8 (T1 / T2 / T2a + T3-T8 方向 C done — commit `56797ff`..`3b905f0`)
- Phase 3:6/6 (T9-T14 done — verify 全绿)
- Follow-up:1/1 (T15 done — AZ async e2e verified `eb277be`)
- 总计:15/15 ✅(代码全 ship;archive 待 user 决定)

## 依赖图

```
T0 (propose) — T1 / T2 / T2a done (B', 统一 pipeline collector)
  │
  └── [方向 C — 废 legacy 全删]
       T3 (删核心栈 + guard tests)
        ├── T4 (config.py 部分删 AZConfig+presets)
        │    ├── T5 (迁 6 prod-adjacent test fixture)
        │    ├── T6 (迁 5 tools/debug/*)
        │    └── T7 (迁 2 profile 脚本 → 统一 pipeline)
        └── T8 (改 phase3{c,d} allowlist)
       T9 (pytest test_az_*) ← T5, T8
        └── T10 (smoke -k az) ← T9
       T11 (grep legacy 删尽) ← T3-T8
       T12 (迁移消费者全过) ← T5, T6, T7
        └── T13 (ruff + line limit) ← T12
       T14 (openspec validate) ← T0
       T15 (async e2e, follow-up) ← pipeline-async-weight-sync change
```

## Total LOC budget (方向 C)

| Component | LOC delta |
|---|---|
| `train_az.py` + `train_loop/` (5 文件) (delete) | ~ -700 |
| `inference_pool.py` + `inference_worker.py` (delete) | ~ -392 |
| `config.py` AZConfig + 3 presets (partial delete) | ~ -150 |
| guard tests (10 文件 delete) | ~ -750 |
| `arena.py` + `config_loader.py` (2 prod 文件 delete) | ~ -190 |
| fixture 迁移 (6 test + 5 debug + 2 profile) | ~ +130 / -90 |
| phase3{c,d} allowlist | ~ -10 |
| **Net code delta** | **~ -2000 (大幅净删,无新 prod code)** |

方向 C 是纯 legacy 清理 — production async/serial 路径(T1/T2 ship)零改动,
净删 ~1800 LOC,统一到 core/actor + 统一 pipeline。async e2e verify (T15) 待
driver weight-sync fix。
