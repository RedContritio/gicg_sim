---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: cfg-toml-restructure-paradigm-scoped
---

# Tasks — cfg-toml-restructure-paradigm-scoped

> Phase 1 = propose(本提案落盘)
> Phase 2 = impl(loader + 10 toml + tests)
> Phase 3 = verify + commit

## Phase 1 — Propose

- [x] **T0**:propose commit — 5 artifact
  - `proposal.md`
  - `design.md`
  - `tasks.md`(本文件)
  - `specs/config-schema/spec.md`(delta — MODIFY N5 + ADD N6 hybrid TOML)
  - `DECISIONS.md`(自主决策点记录)
  - **LOC**:~600(artifacts only)
  - **依赖**:无

## Phase 2 — Implementation

- [x] **T1**:new `training/core/cfg/loader.py` — `load_paradigm_cfg` helper
  - **改动**:
    - 提取 `[paradigm.<name>]` (顶层 paradigm hparam)
    - 提取 `[paradigm.<name>.X]` sub-section (agent / mcts / train / rollout / ...)
    - Merge `[shape]` 共享段 → agent sub-dict(agent override shape per CC-303)
    - Hard break:检测 legacy flat `[paradigm].lr=` scalar key → raise (CC-301)
    - silent ignored `[paradigm.<wrong_name>]` 段 (CC-304)
  - **依赖**:T0

- [x] **T2**:update `training/core/cfg/__init__.py` — export `load_paradigm_cfg`
  - **依赖**:T1

- [x] **T3**:update `training/core/config/loader.py::load_cfg`
  - **改动**:
    - paradigm dispatch 前 call `load_paradigm_cfg(resolved, paradigm)`
    - `_build_dataclass` 接受 `paradigm_flat` 参数,`paradigm=paradigm_flat`
  - **依赖**:T1

- [x] **T4**:update `training/core/config/schema.py::ALLOWED_TOP_LEVEL`
  - **改动**:`+'shape'` 加入合法顶层段
  - **依赖**:T0

- [x] **T5**:new `training/tests/test_cfg_toml_hybrid.py`
  - **Invariants**:
    1. `load_paradigm_cfg` 5 paradigm dispatch 各自取对应 `[paradigm.<name>]`
    2. `[shape]` + `[paradigm.X.agent]` merge:agent override shape(d_model 测试)
    3. 缺 `[shape]` 段 → factory default
    4. 缺 `[paradigm.<name>]` 段 → 全 default (空 dict)
    5. Legacy flat `[paradigm].lr=1e-3` → raise CC-301 error
    6. `[paradigm.<wrong_name>]` silent ignored (dispatch 不被影响)
    7. 8 已有 toml + 2 新 PPO toml = 10 toml `load_cfg` 全部不 raise
    8. Round-trip:`load_paradigm_cfg(load_toml) → from_dict → cfg` 与直接 from_dict 等效
  - **依赖**:T1, T3, T6, T7

- [x] **T6**:restructure 8 existing toml
  - **Files**:
    - `configs/az/default.toml`
    - `configs/az/smoke.toml`
    - `configs/bc/default.toml`
    - `configs/bc/smoke.toml`
    - `configs/cfr/default.toml`
    - `configs/cfr/smoke.toml`
    - `configs/dmc/default.toml`
    - `configs/dmc/smoke.toml`
  - **改动**:
    - 旧 `[paradigm]` 顶层 hparam → `[paradigm.<name>]`
    - 旧 `[paradigm.X]` sub-sections → `[paradigm.<name>.X]`
    - 顶层 `[shape]` 段 OPTIONAL,smoke 不写(用 factory default),default 写共享 d_model
  - **依赖**:T1

- [x] **T7**:new 2 PPO toml
  - **Files**:
    - `configs/ppo/default.toml`
    - `configs/ppo/smoke.toml`
  - **改动**:
    - default:`[shape] d_model=128` + `[paradigm.ppo.agent] d_model=256` (CC-302 override 显示)
    - smoke:`[paradigm.ppo.agent] d_model=32` (smoke 减小)
  - **依赖**:T1

- [x] **T8**:spec delta `openspec/changes/cfg-toml-restructure-paradigm-scoped/specs/config-schema/spec.md`
  - **改动**:MODIFY N5 (configs/ layout 改 hybrid) + ADD N6 (hybrid TOML structure SHALL)
  - **依赖**:T0

## Phase 3 — Verify + commit

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
      -q --no-header
    ```
  - **Pass**:0 new failures vs baseline
  - **依赖**:T1-T8

- [x] **T10**:openspec indices verify
  - **Command**: `.venv/bin/python -m tools._meta.check_openspec_indices`
  - **Pass**: pass
  - **依赖**:T8

- [x] **T11**:commits
  - **C1**:propose — 5 artifact + DECISIONS.md
    - message:`cfg-toml-restructure-paradigm-scoped: propose — hybrid TOML structure + paradigm-scoped sections`
  - **C2**:impl — loader + schema + 10 toml + test + spec delta
    - message:`cfg-toml-restructure-paradigm-scoped: impl — load_paradigm_cfg helper + 10 toml restructure`
  - **依赖**:T9 + T10 green

## 总进度

- Phase 1:1/1(propose)
- Phase 2:8/8(impl)
- Phase 3:3/3(verify + commit)
- 总计:12/12

## 依赖图

```
T0 (propose)
  ├── T1 (loader.py new)
  │    ├── T2 (cfg/__init__.py export)
  │    ├── T3 (config/loader.py dispatch path)
  │    ├── T6 (8 toml restructure)
  │    └── T7 (2 PPO toml new)
  ├── T4 (schema.py ALLOWED_TOP_LEVEL)
  ├── T5 (test_cfg_toml_hybrid.py) ← T1, T3, T6, T7
  ├── T8 (spec delta)
       ├── T9 (sweep verify)
       ├── T10 (openspec verify)
       └── T11 (commits)
```
