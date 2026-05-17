---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: cfg-schema-unification
---

# Tasks — cfg-schema-unification

> Phase 1 = propose(本提案落盘)
> Phase 2 = impl(4 paradigm config + factories + tests + 8 toml)
> Phase 3 = verify + commit

## Phase 1 — Propose

- [x] **T0**:propose commit — 4 artifact
  - `proposal.md`
  - `design.md`
  - `tasks.md`(本文件)
  - `specs/config-schema/spec.md`(delta — ADD invariant N1/N2/N3)
  - `DECISIONS.md`(自主决策点记录)
  - **LOC**:~600(artifacts only)
  - **依赖**:无

## Phase 2 — Implementation

- [x] **T1**:rewrite `training/core/cfg/base.py` — drop `shape` field
  - **改动**:`ParadigmConfigBase` 只留 `version: str = '1.0.0'` + `paradigm: str = ''`,去 `shape: ObsShape` 字段
  - **依赖**:T0

- [x] **T2**:new `training/core/cfg/factories.py` — 4 factory functions
  - **改动**:`make_{az,bc,cfr,dmc}_default_shape() -> ObsShape`,各传 paradigm 历史 d_model + n_cross_layers
  - **依赖**:T0

- [x] **T3**:update `training/core/cfg/__init__.py` — export factories
  - **改动**:加 `from training.core.cfg.factories import make_{az,bc,cfr,dmc}_default_shape`
  - **依赖**:T2

- [x] **T4**:`training/paradigms/az/config.py` — inherit ParadigmConfigBase
  - **改动**:
    - `from training.core.cfg import ObsShape, ParadigmConfigBase`
    - `from training.core.cfg.factories import make_az_default_shape`
    - `AgentShapeCfg = ObsShape` alias
    - `class AZParadigmConfig(ParadigmConfigBase): paradigm = 'az'; agent: ObsShape = field(default_factory=make_az_default_shape)`
    - `from_dict` 增加 version + paradigm 字段验证
  - **依赖**:T1, T2

- [x] **T5**:`training/paradigms/bc/config.py` — same pattern
  - **依赖**:T1, T2

- [x] **T6**:`training/paradigms/cfr/config.py` — same pattern + CFRAgentShapeCfg alias
  - **改动**:`CFRAgentShapeCfg = ObsShape` alias 保 test_cfr_paradigm 兼容
  - **依赖**:T1, T2

- [x] **T7**:`training/paradigms/dmc/config.py` — same pattern
  - **依赖**:T1, T2

- [x] **T8**:`training/tests/test_obs_shape_factories.py` — 4 factory test
  - **Invariants**:
    1. `make_az_default_shape()` returns `ObsShape` with d_model=128 / n_cross_layers=2
    2. BC d_model=32 / n_cross_layers=1
    3. CFR d_model=64 / n_cross_layers=2
    4. DMC d_model=32 / n_cross_layers=1
    5. 4 factory 共享 base fields(n_counter_slots=1832 等)
  - **依赖**:T2

- [x] **T9**:`training/tests/test_cfg_unification.py` — 4 paradigm 共享 ObsShape contract
  - **Invariants**:
    1. AZParadigmConfig 是 ParadigmConfigBase subclass
    2. BCParadigmConfig 是 ParadigmConfigBase subclass
    3. CFRParadigmConfig 是 ParadigmConfigBase subclass
    4. DMCParadigmConfig 是 ParadigmConfigBase subclass
    5. 4 paradigm cfg.agent isinstance ObsShape
    6. AgentShapeCfg / CFRAgentShapeCfg 是 ObsShape alias(`AgentShapeCfg is ObsShape`)
    7. 4 paradigm `cfg.paradigm` 正确(`'az'` / `'bc'` / `'cfr'` / `'dmc'`)
    8. 4 paradigm `cfg.version == '1.0.0'`
  - **依赖**:T4-T7

- [x] **T10**:`training/tests/test_cfg_version_validation.py` — version + paradigm 错误 raise
  - **Invariants**:
    1. AZ `from_dict({'version': '1.5.0'})` → raise(unsupported version)
    2. AZ `from_dict({'paradigm': 'bc'})` → raise(paradigm mismatch)
    3. BC `from_dict({'paradigm': 'az'})` → raise
    4. CFR `from_dict({'paradigm': 'dmc'})` → raise
    5. DMC `from_dict({'paradigm': 'cfr'})` → raise
    6. 4 paradigm `from_dict({})` 默认 paradigm 自身 dispatch key,不 raise
  - **依赖**:T4-T7

- [x] **T11**:update `training/tests/test_cfg_shape.py` — drop shape field test
  - **改动**:
    - 删 `cfg.shape.n_counter_slots == 0` 断言
    - 改 `test_paradigm_config_base_compose_via_subclass` 不用 shape field
  - **依赖**:T1

- [x] **T12**:8 个 `configs/<paradigm>/{default,smoke}.toml`
  - **Files**:
    - `configs/az/default.toml` + `configs/az/smoke.toml`
    - `configs/bc/default.toml` + `configs/bc/smoke.toml`
    - `configs/cfr/default.toml` + `configs/cfr/smoke.toml`
    - `configs/dmc/default.toml` + `configs/dmc/smoke.toml`
  - **依赖**:T4-T7

- [x] **T13**:spec delta `openspec/changes/cfg-schema-unification/specs/config-schema/spec.md`
  - **改动**:ADD invariant N1 (ObsShape unification) + N2 (ParadigmConfigBase compose) + N3 (version field)
  - **依赖**:T0

## Phase 3 — Verify + commit

- [x] **T14**:pytest sweep verify
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -n 4 training/tests/ tools/ \
      --ignore=training/tests/test_cfr_worker.py \
      --ignore=training/tests/test_cfr_parallel_trainer.py \
      --ignore=training/tests/test_eval_service_errors.py \
      --ignore=training/tests/test_eval_service_schema.py \
      --ignore=training/tests/test_eval_service_matchup.py \
      --ignore=training/tests/test_inference_server.py \
      -q --no-header
    ```
  - **Pass**:0 new failures vs baseline
  - **依赖**:T1-T13

- [x] **T15**:openspec indices verify
  - **Command**: `.venv/bin/python -m tools._meta.check_openspec_indices`
  - **Pass**: pass
  - **依赖**:T13

- [x] **T16**:commits
  - **C1**:propose — 4 artifact + DECISIONS.md
    - message:`cfg-schema-unification: propose — 4 paradigm ObsShape unification + version field`
  - **C2**:impl — core/cfg/{base.py, factories.py, __init__.py} + 4 paradigm config.py + 3 test + 1 test update
    - message:`cfg-schema-unification: impl — 4 paradigm ObsShape compose + version validation`
  - **C3**:configs — 8 toml + spec delta
    - message:`cfg-schema-unification: configs — 4 paradigm × 2 preset toml templates + spec delta`
  - **依赖**:T14 + T15 green

## 总进度

- Phase 1:1/1(propose ✅)
- Phase 2:13/13(impl ✅)
- Phase 3:3/3(verify + commit ✅)
- 总计:17/17

## 依赖图

```
T0 (propose)
  ├── T1 (base.py drop shape)
  ├── T2 (factories.py new)
  │    └── T3 (__init__.py export)
  ├── T13 (spec delta)
  └── (4 paradigm 并行)
       ├── T4 (AZ config) ─┐
       ├── T5 (BC config) ─┤
       ├── T6 (CFR config) ┤
       └── T7 (DMC config) ┤
            ├── T8 (factories test)
            ├── T9 (unification test)
            ├── T10 (version test)
            ├── T11 (cfg_shape test update)
            └── T12 (8 toml)
                 ├── T14 (sweep verify)
                 ├── T15 (openspec verify)
                 └── T16 (commits)
```
