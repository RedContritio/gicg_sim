---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: cfr-mp-pool-unification
---

# Tasks — CFR mp pool unification

> Phase 1 (Propose) ship 4 OpenSpec artifact (本 task: draft only)。
> Phase 2 (Implementation) + Phase 3 (Verify) 待 user 确认 D1-D3 决策 +
> design.md flagged uncertainties 后 dispatch。

## Phase 1 — Propose

- [x] **T0**:propose commit — 4 artifact
  - `proposal.md` (why / what / scope / decision summary)
  - `design.md` (4 决策点 D1-D4 + invariant 改动 + risk)
  - `tasks.md` (本文件)
  - `specs/training-architecture/spec.md` (PLACEHOLDER stub — 待 D1 决策
    后扩为 AB14 ADD 或保留 no-SHALL)
  - **LOC**:~ 1500 artifact only
  - **依赖**:无
  - **Status**:本 draft

## Phase 2 — Implementation

> 启动前需 user 确认:D1 选 B (推荐) / D2 选 A (推荐) / D3 选 C (推荐) /
> D4 选 A (推荐) + design.md §10 Flagged uncertainties (1-3) 答案。

- [x] **T1** (条件 D1 选 B):actor_main 加 `episode_runner_factory` 字段
  - **File**:`training/core/actor/actor_process.py`
  - **改动**:
    - signature 加 `episode_runner_factory: Callable[[Any, Any], Any] |
      None = None` + `episode_runner_factory_path: str | None = None`
      (位置:与 `inference_client` / `provider_kwargs` 字段相邻)
    - dispatch block 加:
      ```python
      if episode_runner_factory is None and episode_runner_factory_path is not None:
          episode_runner_factory = resolve_builder(episode_runner_factory_path)
      if episode_runner_factory is not None:
          runner = episode_runner_factory(env_factory, opp_registry)
      else:
          runner = EpisodeRunner(env_factory, opp_registry)
      ```
    - docstring update — 加 calling convention 第 3 类 (CFR pattern,
      Runner factory escape hatch) + Runner 契约说明 (constructor +
      run signature + output picklable)
  - **LOC**:~ 20 net (+ 25 docstring/dispatch - 5 EpisodeRunner direct ctor)
  - **依赖**:T0 + D1 决策确认
  - **Risk**:actor_main signature 23 字段; mitigation: docstring 3-pattern
    table

- [x] **T2** (条件 D1 选 B):actor_main signature 第三 escape hatch 与
  existing `inference_client` / `provider_kwargs` 互斥性 audit
  - **File**:`training/core/actor/actor_process.py`
  - **改动**:验证 `episode_runner_factory` 与 `inference_client` /
    `provider_kwargs` **不互斥** (3 个字段是正交 escape hatch,可以同
    时设 — DMC 设 inference_client 不设 runner factory;PPO 设
    provider_kwargs 不设 runner factory;CFR 设 provider_kwargs +
    runner factory)。 docstring 说明正交性。
  - **LOC**:~ 5 docstring 调整
  - **依赖**:T1

- [x] **T3**:新建 `training/paradigms/cfr/mp_factories.py`
  - **改动**:
    - `build_env_factory(cfg, seed)` — 同 PPO/DMC 模板,从 `cfg.scenario`
      build GicgEnv factory closure (基本 copy PPO `mp_factories.build_
      env_factory` + 适配 CFR scenario 字段)
    - `build_opp_registry(cfg)` — empty registry (CFR traversal 无 opponent,
      satisfies actor_main 强制字段验证)
    - `build_policy(cfg, actor_id)` — `_CFRTraversalPolicy` stub
      (`reset` no-op + `act(obs, mask, provider)` 不被调用,因 CFR runner
      不走 EpisodeRunner-style 单边步)
    - `build_provider(cfg, actor_id, *, weights_shm_info,
      network_blueprint_path)`:
      - WeightsSHM.attach(weights_shm_info)
      - pickle.load(network_blueprint_path) → 2 个 AdvantageNet blueprint
      - initial SHM read 'cfr_adv_p0' / 'cfr_adv_p1' → load_state_dict
      - 内部 build `CFRTraverser(2 net, adv_cols, strat_col, val_col,
        traversal_cfg, rng)` + collector buffers
      - 返 `_CFRActorProvider(nets, traverser, shm, cols)`
    - `cfr_spec_sampler(cfg, actor_id)` — `EpisodeSpec` encode (per
      design.md D1.B convention):
      - `scenario_seed = _derive_seed(cfg.meta.seed, actor_id, seq)`
      - `starting_player = seq % 2` (alternate)
      - `opponent_id = 'cfr_traverser'` (sentinel)
      - `epsilon = float(iteration)` (worker-local iteration counter)
    - `class CFRTraversalRunner`:
      - `__init__(env_factory, opp_registry)` — opp_registry 忽略
      - `run(spec, policy, provider)`:
        - `iteration = int(spec.epsilon); traverser_p = int(spec.starting_player)`
        - `env = env_factory(spec.scenario_seed)`
        - `provider.traverser.traverse(env, traverser_p, iteration)`
        - `batch = drain_single_traversal(provider.adv_cols,
          provider.strat_col, provider.val_col, traverser_p)`
        - 返 `_CFRRunnerOutput(transitions=[], cfr_batch=batch, ...)`
    - `build_cfr_traversal_runner(env_factory, opp_registry)` factory
    - `class _CFRActorProvider`:
      - forward / update_weights (SHM poll 'cfr_adv_p0' + 'cfr_adv_p1' →
        load_state_dict on version bump) / current_version / close
    - `class _CFRRunnerOutput`:
      - `transitions: list = []` (empty,EpisodeRunner contract surface)
      - `cfr_batch: CFRGameBatch` (real payload)
      - picklable dataclass
  - **LOC**:~ 250
  - **依赖**:T1, T2

- [x] **T4**:新建 `training/paradigms/cfr/_async.py`
  - **改动**:
    - `class CFRAsyncCollector` implements Collector protocol:
      - `__init__(cfg, paradigm_cfg, network, env_factory)`:
        - WeightsSHM(owner=True) build + write 'cfr_adv_p0' /
          'cfr_adv_p1' (sd from `network.advantage_head(0)` /
          `network.advantage_head(1)`)
        - tempfile pickle.dump network blueprint (2 net) → np_path
        - IPCQueue(maxsize=...) build
        - Runtime(cfg, weights_shm) build
        - runtime.start_actors(n_actors=cfg.pipeline.num_actors,
          actor_kwargs_factory=lambda i: dict(
            build_env_factory_path=...,
            build_opp_registry_path=...,
            build_policy_path=...,
            build_provider_path=...,
            spec_sampler_path=...,
            episode_runner_factory_path='training.paradigms.cfr.mp_factories.build_cfr_traversal_runner',
            transition_queue=ipc_queue,
            push_episode_record=True,  # CFRRunnerOutput is the payload
            provider_kwargs={
              'weights_shm_info': weights_shm.serialize_for_worker(['cfr_adv_p0', 'cfr_adv_p1']),
              'network_blueprint_path': str(np_path),
            },
          ))
      - `collect(n_units, provider)`:
        - drain N (= n_units or default 64) `_CFRRunnerOutput` from
          IPCQueue (with `_drain_timeout_s = 60.0` SLA)
        - 提取 cfr_batch list, 返 `CollectorOutput(transitions=[],
          runtime_metrics={'cfr_batches': cfr_batch_list,
          'cfr_iteration': self._iter_seq}, n_units=total_samples)`
      - `sync_weights(network)`:
        - publish `network.advantage_head(0).state_dict()` → SHM 'cfr_adv_p0'
        - publish `network.advantage_head(1).state_dict()` → SHM 'cfr_adv_p1'
        - bump weights_version
      - `state_dict / load_state_dict / close` 同 PPO _async pattern
  - **LOC**:~ 150
  - **依赖**:T3

- [x] **T5**:改 `training/paradigms/cfr/paradigm.py:make_collector` 加
  mode dispatch
  - **File**:`training/paradigms/cfr/paradigm.py`
  - **改动**:
    - `make_collector(cfg, env_factory, network, opp_pool)` 头部加:
      ```python
      mode = getattr(cfg.pipeline, 'mode', 'serial')
      if mode == 'async':
          from training.paradigms.cfr._async import CFRAsyncCollector
          return CFRAsyncCollector(cfg, self._resolve_pcfg(cfg), network, env_factory)
      if mode != 'serial':
          raise ValueError(f"CFRParadigm.make_collector: cfg.pipeline.mode must be 'serial' or 'async', got {mode!r}")
      ```
    - 现有 `CFRTraversalCollector` 路径保留作 serial fallback
    - docstring update
  - **LOC**:~ 10
  - **依赖**:T4

- [x] **T6**:删 `training/paradigms/cfr/parallel_trainer.py` (-170 LOC)
  + `training/paradigms/cfr/worker.py` (-203 LOC) + 修
  `training/paradigms/cfr/collector.py:CFRAsyncCollector` NotImplementedError
  stub (-65 LOC,删 class definition line 205-266)
  - **改动**:
    - `parallel_trainer.py` delete file
    - `worker.py` delete file
    - `collector.py` 删 `CFRAsyncCollector` stub class (line 205-266)
      及对应 import / module docstring 中 placeholder 段落
  - **LOC**:净 -438
  - **依赖**:T5
  - **Risk**:grep production callers — 已 audit 仅 2 test file 用,删
    安全

- [x] **T7**:删 + 新建 tests
  - **改动**:
    - 删 `training/tests/test_cfr_parallel_trainer.py` (-186)
    - 删 `training/tests/test_cfr_worker.py` (-162)
    - 新建 `training/tests/test_cfr_mp_factories.py` (~ 80 LOC):
      - `test_build_provider_constructs_traverser` — mock SHM + blueprint
        path,验 build_provider 返 _CFRActorProvider 有 nets / traverser
      - `test_cfr_traversal_runner_runs_one_traversal` — fake env factory,
        mock CFRTraverser,验 runner.run → drain → _CFRRunnerOutput
        with non-empty cfr_batch
      - `test_cfr_spec_encode_roundtrip` — spec_sampler encode + runner
        decode 一致 (iteration / traverser_p)
      - `test_cfr_spec_sampler_monotonic_seq` — 每 actor seq 单调
    - 新建 `training/tests/test_cfr_async_mp_e2e.py` (~ 120 LOC,
      `@pytest.mark.smoke_full`):
      - 2 actor + 1 iter (8 traversal) + verify cfr_batches drained 完整
        + verify sync_weights SHM read 一致 + clean shutdown
      - 仿 PPO `test_ppo_async_mp_e2e.py` (本 session 已 ship) + DMC
        `test_go_subprocess_5ep_e2e.py` e2e pattern
      - cfg 用 small scenario (smoke 6-card pool / max_rounds=2,与
        configs/cfr/smoke.toml 对齐)
  - **LOC**:净 -148 (- 348 + 200 新)
  - **依赖**:T6

## Phase 3 — Verify

- [x] **T8**:`pytest training/paradigms/cfr/tests/ training/tests/test_cfr_
  mp_factories.py training/core/actor/tests/`
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -n 4 \
      training/paradigms/cfr/tests/ \
      training/tests/test_cfr_mp_factories.py \
      training/core/actor/tests/ -q
    ```
  - **Pass**:0 new failures vs baseline
  - **依赖**:T1-T7

- [x] **T9**:`pytest -m smoke -k cfr`
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -m smoke training/tests/ -q -k cfr
    ```
  - **Pass**:CFR serial smoke 不 break
  - **依赖**:T8

- [x] **T10**:`pytest -m smoke_full training/tests/test_cfr_async_mp_e2e.py
  + test_cfr_smoke_full.py`
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -m smoke_full \
      training/tests/test_cfr_async_mp_e2e.py \
      training/tests/test_cfr_smoke_full.py -v
    ```
  - **Pass**:async mp e2e 全过 (wall ≤ 30s Mac) + serial smoke_full driver
    e2e 不 break
  - **依赖**:T9

- [x] **T11**:`ruff format` + line limit hook 验
  - **Command**:
    ```bash
    .venv/bin/ruff format \
      training/paradigms/cfr/mp_factories.py \
      training/paradigms/cfr/_async.py \
      training/paradigms/cfr/paradigm.py \
      training/paradigms/cfr/collector.py \
      training/core/actor/actor_process.py \
      training/tests/test_cfr_mp_factories.py \
      training/tests/test_cfr_async_mp_e2e.py
    .venv/bin/python -m tools._meta.check_line_limits | grep -E "(cfr|actor_process)" || echo "PASS"
    ```
  - **Pass**:format 0 changes, line limit 全文件 ≤ 阈值
  - **依赖**:T10

- [x] **T12**:openspec validate
  - **Command**:
    ```bash
    .venv/bin/python -m tools._meta.check_openspec_indices --staged
    ```
  - **Pass**:`cfr-mp-pool-unification/specs/training-architecture/spec.md`
    格式 OK
  - **依赖**:T0 (artifact 落盘 + D1 决策后 spec 扩写)

## 总进度

- Phase 1:1/1
- Phase 2:7/7
- Phase 3:5/5 (mp e2e 2 passed 2.7s + serial driver smoke_full 1 passed 33s)
- 总计:13/13
- 附加:IPCQueue.close cancel_join_thread 修复 (f219e02,SIGKILL'd-writer hang
  根因,跨 5 paradigm shared infra) + code review 跟进 (416a066)

## 依赖图

```
T0 (propose: 4 artifacts) ← 本 task draft
  ↓ (waiting D1-D3 decision + §10 uncertainty 答案)
T1 (actor_main: episode_runner_factory) ← D1=B
  ↓
T2 (escape hatch 正交性 audit)
  ↓
T3 (mp_factories.py 新建) ← D2=A + D4=A
  ↓
T4 (_async.py 新建) ← D3=C
  ↓
T5 (paradigm.py make_collector mode dispatch)
  ↓
T6 (删 parallel_trainer.py + worker.py + collector.py stub)
  ↓
T7 (tests 删 + 新建)
  ↓
T8 (pytest unit verify)
  ↓
T9 (pytest smoke -k cfr)
  ↓
T10 (pytest smoke_full mp e2e + driver e2e)
  ↓
T11 (ruff format + line limit)
  ↓
T12 (openspec validate)
```

## LOC budget summary

| Item                                  | LOC      |
|---------------------------------------|----------|
| actor_main: episode_runner_factory    | +20      |
| mp_factories.py 新建                  | +250     |
| _async.py 新建                        | +150     |
| paradigm.py make_collector dispatch   | +10      |
| 删 parallel_trainer.py                | -170     |
| 删 worker.py                          | -203     |
| 删 collector.py:CFRAsyncCollector stub| -65      |
| 删 test_cfr_parallel_trainer.py       | -186     |
| 删 test_cfr_worker.py                 | -162     |
| 新 test_cfr_mp_factories.py           | +80      |
| 新 test_cfr_async_mp_e2e.py           | +120     |
| **Code 净**                           | **-156** |
| OpenSpec artifact (proposal/design/tasks/spec) | +1500 |
| **总 (含 artifact)**                  | **+1344**|
