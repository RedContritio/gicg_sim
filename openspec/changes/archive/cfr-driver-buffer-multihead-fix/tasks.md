---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: cfr-driver-buffer-multihead-fix
---

# Tasks — cfr-driver-buffer-multihead-fix

3 phase 实施(propose / impl / verify gates)。

## Phase 1 — Propose(本文件 + design + spec delta)

- [x] T1.1 propose.md(已写本文件父目录)
- [x] T1.2 design.md(初始 ~80 行决策树 + 替代方案 tradeoffs)
- [x] T1.3 specs/paradigm-cfr/spec.md delta — ADD C6.4 smoke-only stub
  buffer 在 frozen-research tier 允许

## Phase 2 — Implement(test-only,production CFR 不动)

- [x] T2.1 `training/paradigms/cfr/paradigm.py` 修改 `CFRParadigm.make_buffer`
  加 env flag 分支:`os.environ.get('GICG_CFR_SMOKE_STUB_BUFFER') == '1'`
  return `_SmokeStubBuffer` instead of `_CFRBufferBundle`(lazy import 防
  污染 production import 链)
- [x] T2.2 `training/tests/_cfr_smoke_stub.py` 新增 ~108 LOC —
  `_SmokeStubBuffer` 实现 generic Buffer protocol;
  `training/tests/test_cfr_smoke_full.py` 移除 `@pytest.mark.skip` +
  加 protocol-assert test
- [x] T2.3 `training/tests/smoke_full_template.py` 加 `extra_env` +
  `max_steps` optional 参数;test 调时传 `extra_env={'GICG_CFR_SMOKE_STUB_BUFFER':
  '1'}` + `max_steps=30`(initial run cap,resume 跑到 cfg n_iterations=50 产生
  新 ckpt)
- [x] T2.4 `test_smoke_stub_buffer_satisfies_protocol` 验证
  `isinstance(stub, Buffer)`(runtime_checkable assert)

## Phase 3 — Verify gates(hard)

- [x] T3.1 `pytest training/tests/test_cfr_smoke_full.py -v -m smoke_full
  --tb=short` PASS(driver train 30 step → 3 ckpt;resume 跑到 step 50
  → +2 new ckpt,总 5 文件)
- [x] T3.2 `pytest training/tests/test_cfr_*.py -v --tb=short` 146 passed
  无 regression(production CFR test 全 pass)
- [x] T3.3 `test_cfr_smoke.py::test_cfr_paradigm_smoke` 仍 pass(baseline
  smoke 不动)
- [x] T3.4 默认 `pytest training/tests/ -q` 1004 passed / 3 skipped /
  0 fail — 0 regression
- [x] T3.5 Line limit:`_cfr_smoke_stub.py` 108(<300)/
  `test_cfr_smoke_full.py` 77(<500)/ `paradigm.py` 262(<300,加 ~12 行
  从 250)/ `smoke_full_template.py` 219(<300,加 18 行)
- [x] T3.6 `tools/_meta/check_openspec_indices.py` 通过(无 output)

## Out of scope(follow-up)

- CFR unfreeze + 切真正 single-head buffer(需独立 OpenSpec change
  unfreezing C6.3 + 重写 _CFRBufferBundle 或 driver multi-head 支持)
- 其他 4 个 smoke_full skip(各自独立 follow-up:az-pool-spec-type-fix /
  ppo-rollout-card-pool-none-fix / bc-smoke-dataset-fixture)
