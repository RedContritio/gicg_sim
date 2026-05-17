---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: env-factory-unification
---

# Tasks — env-factory-unification

> Phase 1 = propose(本提案落盘)
> Phase 2 = impl(rewrite + migrate)
> Phase 3 = verify + commit

## Phase 1 — Propose

- [x] **T0**:propose commit — 4 artifact 落盘
  - `proposal.md`
  - `design.md`
  - `tasks.md`(本文件)
  - `specs/training-architecture/spec.md`(delta)
  - **LOC**:~370(artifacts only)
  - **依赖**:无

## Phase 2 — Implementation

- [x] **T1**:verify `ObsConfig.to_engine_json()` 现存
  - **方法**:grep `training/core/scenario.py:24` 已确认
  - **LOC**:0(只是 verify)
  - **依赖**:T0

- [x] **T2**:rewrite `training/core/env_factory.py` 为 canonical 3-arg
  - **签名**:`make_env_factory(cfg, obs_config_json: Optional[dict], master_seed: int) -> Callable[[int], GicgEnv]`
  - **删除**:`master_seed=None` default + `cfg.meta.seed` magic 读取
  - **新增**:docstring 注明 `cfg` 只读 `cfg.scenario`,paradigm-agnostic
  - **LOC**:~+50/-42
  - **依赖**:T1

- [x] **T3**:add `training/tests/test_env_factory_unified.py`
  - **Invariants**:
    1. `obs_config_json=None` path:env 用 engine default shuffle
    2. `obs_config_json=cfg.obs.to_engine_json()` path:shuffle 字段
       forward 到 env
    3. `master_seed` override:`env_factory(0)` 和 `env_factory(5)`
       不同 seed,reset 后 hash 不同
    4. `cfg.scenario` 字段(`max_rounds` / `fix_dice` / `obs_mask` /
       `deck_padding` / `pool`)forward 到 env
  - **LOC**:~+80
  - **依赖**:T2

- [x] **T4**:migrate `training/paradigms/az/train_loop/async_loop.py`
  - **改动**:
    - import: `from training.core.env_factory import make_env_factory`(去 `_legacy`)
    - call site `:69`:`make_env_factory(config)` → `make_env_factory(config, config.obs.to_engine_json(), master_seed=config.seed)`
  - **LOC**:~+2/-2
  - **依赖**:T2

- [x] **T5**:migrate `training/tests/test_scenario_sampling.py`
  - **改动**:
    - import line `:192`:去 `_legacy`
    - call site `:210`:`make_env_factory(cfg)` → `make_env_factory(cfg, cfg.obs.to_engine_json(), master_seed=cfg.seed)`
  - **LOC**:~+2/-2
  - **依赖**:T2

- [x] **T6**:migrate `tools/run.py` + 删 `_build_env_factory`
  - **改动**:
    - import: `from training.core.env_factory import make_env_factory`
    - 删除 `_build_env_factory` 函数(~27 LOC)
    - `:81` 改:`env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)`
  - **LOC**:~+2/-27
  - **依赖**:T2

- [x] **T7**:`git rm training/core/env_factory_legacy.py`
  - **LOC**:-44/0
  - **依赖**:T4 + T5(callers 已迁完)

## Phase 3 — Spec sync + verify + commit

- [x] **T8**:sync `openspec/specs/training-architecture/paradigm-onboarding.md`
  - **改动**:
    - § 3 layout 段:删 `env_factory_legacy.py` 字样
    - § 9 revision triggers:更新 trigger 状态
    - add 新 § "Env factory 公共契约"(简短,5-10 行)指向
      `core/env_factory.py` canonical signature
  - **LOC**:~+12/-3
  - **依赖**:T7

- [x] **T9**:pytest sweep verify
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -n 4 training/tests/ tools/ \
      --ignore=training/tests/test_cfr_worker.py \
      --ignore=training/tests/test_cfr_parallel_trainer.py \
      --ignore=training/tests/test_eval_service_errors.py \
      --ignore=training/tests/test_eval_service_schema.py \
      --ignore=training/tests/test_eval_service_matchup.py \
      --ignore=training/tests/test_inference_server.py \
      -q
    ```
  - **Additional smoke**:
    - `pytest -k 'train_az or az_smoke' -n 4` — AZ hot path 不回归
    - `pytest training/tests/test_env_factory_unified.py -v` — 新测试 3 invariant green
    - `grep -rn env_factory_legacy --include='*.py' .` — 0 hit
  - **Pass**:pre-existing sandbox-ignored tests 之外全 pass;新加 4
    test pass
  - **LOC**:0(只跑测试)
  - **依赖**:T2-T8

- [x] **T10**:commits
  - **C1**:propose — 4 artifact
    - message:`env-factory-unification: propose — canonical 3-arg make_env_factory + retire _legacy`
  - **C2**:impl — env_factory rewrite + 3 migration + git rm + test + spec sync
    - message:`env-factory-unification: impl — canonical 3-arg + 3 site migration + rm _legacy`
  - **LOC**:per commit ~50-200(impl 较大)
  - **依赖**:T9 green

## 总进度

- Phase 1:4/4 (propose artifacts ✅)
- Phase 2:7/7 (impl ✅)
- Phase 3:3/3 (spec sync + verify + commit ✅)
- 总计:14/14

## 依赖图

```
T0(propose)
  └── T1(verify ObsConfig.to_engine_json)
       └── T2(rewrite env_factory.py)
            ├── T3(test_env_factory_unified.py)
            ├── T4(async_loop.py migration)
            ├── T5(test_scenario_sampling.py migration)
            └── T6(tools/run.py migration)
                 └── T7(git rm env_factory_legacy.py)
                      └── T8(spec sync paradigm-onboarding.md)
                           └── T9(pytest sweep verify)
                                └── T10(commits)
```
