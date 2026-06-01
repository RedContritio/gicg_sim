---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: pipeline-async-weight-sync
---

# Tasks — pipeline async weight sync

> 按 commit-ready 边界拆分 + 依赖链。每步测试过再开始下一步。
> 当前 task 编排按 D1=A / D2=统一 / D3=4 全做(详 design.md)。

## Phase 1 — Propose

- [x] **T0**:propose commit — 4 artifact(proposal / design / tasks / spec delta)。

## Phase 2 — Implementation

- [x] **T1** (DONE 2026-06-01):`StepPlan.sync_weights` flag + driver honor
  - **实现注记**:gating 逻辑提取为 module-level helper
    `pipeline._maybe_sync_weights(plan, collector, network)`(非内联)— `run_pipeline`
    从未被单测,提取 helper 让 test 真调 production code(非 logic-mirror 副本,避开
    `test_pipeline_opp_pool_add_snapshot` 的 anti-pattern)。4 unit(flag True/False ×
    collector 有/无 method,含 default-False invariant)PASS + 5 paradigm smoke 无
    regress + ruff clean。位置正确性(train 后 clear 前)由 T4 async e2e 覆盖。
  - **File**:`training/core/protocols.py` + `training/core/pipeline.py`
  - **改动**:
    - `StepPlan` 加 `sync_weights: bool = False`(mirror `clear_buffer_after_train`,
      docstring 说明 paradigm-declared async weight republish epilogue)。
    - `run_pipeline` train block 后(L153 `state.after_train` 之后、L159
      `clear_buffer_after_train` 之前)加:
      ```python
      if plan.sync_weights and hasattr(collector, 'sync_weights'):
          collector.sync_weights(network)
      ```
  - **Test**:`test_pipeline_sync_weights_gate.py`(NEW)— mock collector(records
    `sync_weights` calls)× StepPlan.sync_weights True/False → 验 honor;无
    `sync_weights` 的 collector(serial stub)不 crash(hasattr guard)。
  - **LOC**:~ +6 prod + ~40 test
  - **依赖**:T0
  - **Risk**:位置必须在 train 后、collect 前(下轮 actor collect 拿新权重);放
    eval/ckpt 后也行但语义弱。

- [x] **T2** (DONE 2026-06-01):cadence cfg 字段统一
  - **实现注记**:(1) default = **0**(D-c 沿用 DMC 现 `weight_sync_every_steps`
    default,非 propose 时写的 10)— 保持 DMC 行为不变,async mode 下 `max(1, 0)`=每
    train iter sync。(2) **configs/ 无需改**:grep 全仓 0 toml 引用
    `weight_sync_every_steps`(`stage3_b_v_legacy.toml` 不含该字段,吃 default)。
    (3) DMC rename 安全:`weight_sync_every_steps` 此前**无任何 .py reader**(driver
    缺 sync 逻辑 = weight-sync gap 本身),production code 0 残留。新
    `test_paradigm_sync_weights_cadence_cfg.py`:6 unit(4 paradigm default-0
    parametrize + DMC rename field-level + strict-loader reject)PASS + DMC/AZ
    config regression + 5 paradigm smoke 无 regress + ruff clean。
  - **File**:`training/paradigms/{az,cfr,ppo}/config.py` + `training/paradigms/dmc/config.py`
    + `configs/dmc/stage3_b_v_legacy.toml`
  - **改动**:
    - AZ `AZParadigmConfig` / CFR `CFRParadigmConfig` / PPO `PPOParadigmConfig`
      各加 `sync_weights_every_train_steps: int = 10`(unified 路径读它;AZ legacy
      `AZConfig.sync_weights_every_train_steps` 已有,语义对齐)。
    - DMC `DMCParadigmConfig.weight_sync_every_steps` → rename
      `sync_weights_every_train_steps`(语义同:`0/1`=每 train iter)。
    - `configs/dmc/stage3_b_v_legacy.toml` 同步改字段名(strict loader unknown-key
      会 fail,grep 验)。
  - **Test**:各 paradigm config from_dict 测试加 cadence 字段断言(若已有 cfg
    roundtrip test,扩;否则薄加)。
  - **LOC**:~ +4 cfg fields + 1 rename + 1 toml
  - **依赖**:T0
  - **Risk**:DMC rename breaking — grep `weight_sync_every_steps` 全仓确认无
    其它引用残留(collector / step_schedule / tests)。

- [x] **T3** (DONE 2026-06-01):4 paradigm `step_schedule` 翻 `sync_weights` bit
  - **实现注记**:cadence+mode gating 提取为共享 helper
    `protocols.async_sync_weights_due(cfg, state, sync_every)`(DRY,非各 paradigm
    内联 2 行),4 paradigm steady 分支各调 1 行。新
    `test_step_schedule_sync_weights_bit.py`:helper 真测(serial 恒 False /
    async cadence-0=每 iter / N 边界 / 缺 mode default serial)+ 4 paradigm wiring
    parametrize(async steady→True / serial→False;load smoke +
    `object.__setattr__` 强制 mode 绕 CS1.1「async 需 [eval]」全-cfg 校验)。修
    CFR/PPO 2 个 stub cfg 补 `pipeline.mode`(step_schedule 新读 cfg.pipeline,按
    严格契约修 stub,非把 helper 写成 dead-defensive)。12 T3 unit + 125 paradigm +
    5 smoke + ruff clean。
  - **File**:`training/paradigms/{az,dmc,cfr,ppo}/paradigm.py`
  - **改动**:各 `step_schedule` 的 steady-train 分支(已 `train=True` 那支)按:
    ```python
    sync = (getattr(cfg.pipeline, 'mode', 'serial') == 'async'
            and state.train_steps % max(1, pcfg.sync_weights_every_train_steps) == 0)
    ```
    设 `StepPlan(..., sync_weights=sync)`。warm-up / done 分支不翻(默认 False)。
  - **Test**:per-paradigm step_schedule unit — async mode + train_steps 序列 →
    验 sync bit 在 cadence 边界翻;serial mode 恒 False;warm-up 恒 False。
    走 parametrize / base template(per `feedback_symmetric_tests`)。
  - **LOC**:~ +8 each × 4 = +32 prod + per-paradigm test
  - **依赖**:T1, T2
  - **Risk**:CFR step_schedule 是 traversal cadence(非 episode),sync 语义同
    (advantage net republish);确认 CFR `step_schedule` 有 train 分支可挂。

- [x] **T4** (DONE 2026-06-01):e2e — driver 集成 + 真-spawn republish 双验
  - **实现注记**:原计划「扩 test_dmc/cfr_async_mp_e2e 断言 actor version」失准
    (dmc 文件不存在;现有 CFR e2e 直调 collector.sync_weights **不经 driver**)。
    拆两层:
    (1) **driver-integration e2e**(新 `test_pipeline_async_weight_sync_e2e.py`):
    fake paradigm + spy collector **真跑 run_pipeline async 完整循环** → 验 driver
    跨 train iter 调 collector.sync_weights(serial 不调)。这是 weight-sync gap 核心
    修复的端到端证明(step_schedule bit → driver honor → collector.sync_weights),
    **sandbox-safe**(无 spawn),2 unit PASS。
    (2) **真-spawn republish**(本 session 实跑现有 CFR async mp e2e smoke_full):
    1-actor(1.6s)+ 2-actor(1.5s)真 spawn + collect + collector.sync_weights bump
    `_weights_version`(SHM 2-slot republish)+ clean shutdown,**本环境 spawn 未被
    sandbox block**,PASS。
    全链覆盖:T3(bit)× T1+T4.1(driver→sync_weights)× T4.2(sync_weights→actor SHM
    republish)。真 run_pipeline async spawn 整链组合 = T7 follow-up(run 149 长跑)。
  - **File**:`training/tests/test_pipeline_async_weight_sync_e2e.py` (NEW)
  - **依赖**:T1, T2, T3

## Phase 3 — Verify

- [x] **T5** (DONE 2026-06-01):spec delta 落 change dir + index 校验
  - **实现注记**:change `specs/training-architecture/spec.md`(3 SHALL:driver
    republish / StepPlan.sync_weights field / async collector contract)的 Code+Test
    references 更新为实际实现(`async_sync_weights_due` helper / default=0 / 实际
    test 名)。主 `pipeline.md` sync 在 archive 时做。`check_openspec_indices` PASS。
  - **依赖**:T0

- [x] **T6** (DONE 2026-06-01):全 async paradigm + driver pytest + DMC rename grep
  - **结果**:`pytest -n 4 test_pipeline* test_step_schedule* test_paradigm_sync_weights*
    test_*_async* test_*_smoke* -m "not smoke_full"` → **95 passed, 3 skipped, 0 fail**;
    grep `weight_sync_every_steps` production **0 hit**(仅 rename-test 字符串);index OK。
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -n 4 training/tests/test_pipeline*.py \
      training/tests/test_*_async*.py training/tests/test_*_smoke* -q -m "not smoke_full"
    grep -rn "weight_sync_every_steps" training/ tools/ configs/ | grep -v __pycache__
    ```
  - **Pass**:0 new failures;grep 0 hit(DMC rename 全切)。
  - **依赖**:T1, T2, T3, T4

- [ ] **T7 (follow-up,非本 change gate)**:re-run run 149(DMC async)验证 collapse
  关联
  - **改动**:0 code。fix ship 后 re-run `configs/dmc/stage3_b_v_legacy.toml`
    对比 collapse 是否消失 / 收敛改善 → 确认 weight sync gap 是否 run 149 collapse
    root cause。 结果落 memory `project_stage3_pilot_policy_collapse_2026_05_28`。
  - **依赖**:T6(fix ship)
  - **注**:本 change 的 acceptance 是 weight sync 正确性(T1-T6),collapse 验证是
    independent follow-up(需 GPU box + 长跑)。

## 总进度

- Phase 1:1/1
- Phase 2:4/4 (T1-T4 done)
- Phase 3:2/3 (T5/T6 done;T7 follow-up — GPU box run-149 re-run)
- 总计:7/8 (仅余 T7 GPU-box follow-up)

## 依赖图

```
T0 (propose)
  ├── T1 (StepPlan.sync_weights + driver honor)
  │    └── T3 (4 paradigm step_schedule) ← T1, T2
  │         └── T4 (e2e version bump)
  ├── T2 (cadence cfg 统一) → T3
  ├── T5 (spec delta) ← T0
  ├── T6 (pytest + grep) ← T1-T4
  └── T7 (run 149 re-run, follow-up) ← T6
```
