# bc-pipeline-collect-gate-fix — tasks

Single-line production fix + 1 test assertion + spec invariant lock。

## T1 — Phase 1 Propose

- [x] T1.1 `proposal.md`(本 change 顶层,why + what + scope + decision summary)
- [x] T1.2 `design.md`(初始简,Phase 3 archive 时改 retrospective)
- [x] T1.3 `specs/training-architecture/spec.md` delta — ADD invariant
  about pipeline collect gate semantics(`plan.collect` 是 driver-side
  唯一 gate;`plan.n_episodes` 是 collector-internal contract)

## T2 — Phase 2 Implement(production single-line + test assertion + 1 deeper integration fix)

- [x] T2.1 Edit `training/core/pipeline.py:83`:gate 从
  `if plan.collect and plan.n_episodes > 0:` relax 为 `if plan.collect:`。
  inline comment 说明 collector 自身 decide n_units(BC dataset-driven,
  非 BC EpisodeRunner-driven)
- [x] T2.2 Edit `training/tests/test_bc_smoke_full.py`:在 `verify_ckpt_files`
  call 后加 metrics assertion — read `metrics.jsonl` 最后一行 iter,
  assert `train_steps > 0`(锁住 collector 调用 + train batch 走通)
- [x] T2.3 删 / 更新 `test_bc_smoke_full.py` docstring 的 KNOWN CONCERN
  段(本 change 闭此 concern,docstring 改写记录 fix 来源 reference 即可)
- [x] T2.4(**SCOPE EXTENSION — discovered during T3.1**)Edit
  `training/core/buffer/dataset.py` + `training/paradigms/bc/paradigm.py`:
  T2.1 gate relax 暴露 second integration bug — `DatasetBuffer.sample`
  return `data={'transitions': [Transition,...]}` 但 `BCLoss.compute`
  expect `data['fields']`。Add optional `batch_builder` ctor arg to
  `DatasetBuffer`(callable indices → fields dict);`BCParadigm.make_buffer`
  传入 `collector.build_batch` 让 sample 直接产 `{'fields': ...}` 喂
  BCLoss。Backward-compatible default(无 builder 时 fallback `data={'transitions':...}`
  保兼容现有 `test_core_buffer_replay.test_dataset_sample`)

## T3 — Phase 2 Verification gates(hard)

- [x] T3.1 `pytest training/tests/test_bc_smoke_full.py -v -m smoke_full
  --tb=short` PASS(BC smoke_full 实际训练 19s wall + assertion 通过)
- [x] T3.2 `pytest training/tests/test_dmc_smoke_full.py -v -m smoke_full
  --tb=short` PASS(非 BC paradigm regression check — DMC `n_episodes>0`
  path 不破)
- [x] T3.3 `pytest training/tests/test_cfr_smoke_full.py -v -m smoke_full
  --tb=short` PASS(CFR stub buffer 路径 verify;CFR `step_schedule` 也
  emit `n_episodes>0`)— T3.2 + T3.3 combined 258s wall(DMC dominant)
- [x] T3.4 `pytest training/tests/test_bc_paradigm.py test_bc_smoke.py
  test_bc_hard_target.py` 29/29 pass(BC 其它 test 无 regression)
- [x] T3.5 `pytest training/tests/test_core_buffer_replay.py 5 paradigm
  test files` 153/153 pass(buffer + 5 paradigm core test 无 regression)
- [x] T3.6 `pytest -n 4 training/tests/ -q` 1004 passed / 3 skipped
  (pre-existing per memory `project_pre_existing_sandbox_failures_2026_05_17`)
  / 0 failed — 全 sweep 0 regression
- [x] T3.7 `tools._meta.check_openspec_indices` 0 violation(silent)
- [x] T3.8 `tools._meta.check_line_limits` 9 pre-existing violators
  (grandfathered);新增/修改文件全 < limit(pipeline.py 155 / dataset.py
  108 / paradigm.py 164 / test_bc_smoke_full.py 176)
- [x] T3.9 `ruff format --check` 通过(4 files already formatted)

## T4 — Phase 3 Archive

- [x] T4.1 `design.md` 改 retrospective(154 行,< 200 cap;5 sections:
  Verdict / What we built / Tradeoffs revisited / Surprises / Spec delta
  summary + DECISIONS index)
- [x] T4.2 验证 all T1/T2/T3 boxes 都 `[x]`(T1.1-T1.3 + T2.1-T2.4 +
  T3.1-T3.9 全 `[x]`)
- [x] T4.3 `tools._meta.openspec_archive --change-id
  bc-pipeline-collect-gate-fix --no-commit --specs-merged`(spec delta 已
  manually merge 到 `pipeline.md` §3 + `spec.md` Status)
- [x] T4.4 单 commit:`openspec archive: bc-pipeline-collect-gate-fix`

## Estimated workload

| Item | LOC |
|---|---|
| `training/core/pipeline.py:83` gate relax + inline comment | ~3 / -1 |
| `training/tests/test_bc_smoke_full.py` metrics assertion + docstring update | ~25 / -10 |
| `openspec/changes/.../specs/training-architecture/spec.md` delta | ~15 |
| `proposal.md` + `tasks.md` + `design.md`(propose + archive retrospective) | ~250 |
| **Total** | **~290 LOC**(~30 code + ~260 docs) |
