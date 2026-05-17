---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: paradigm-smoke-full-tier
---

# Tasks — paradigm-smoke-full-tier

3 phase 实施。**严格按顺序**(Phase 1 完 → Phase 2 → Phase 3 verify hard gate)。

## Phase 1 — Infrastructure(pyproject + template + spec delta)

- [x] T1.1 `pyproject.toml` 加 `markers.smoke_full = "..."` + `addopts = "-m 'not smoke_full'"`(默认排除 collection)
- [x] T1.2 `training/tests/smoke_full_template.py` 新增 ~80-120 LOC —
  `run_paradigm_train_via_driver` + `verify_ckpt_files` + `resume_and_continue`
  3 个 helper,全 subprocess `tools.run`
- [x] T1.3 `openspec/changes/paradigm-smoke-full-tier/specs/training-architecture/spec.md`
  新增 — ADD invariant A1.6 smoke_full tier 契约

## Phase 2 — Per-paradigm cfg + test files

- [x] T2.1 `configs/dmc/smoke_full.toml` 新增 — extends smoke.toml +
  `save_every=30` + `total_frames=2000`
- [x] T2.2 `configs/az/smoke_full.toml` 新增 — extends smoke.toml +
  cadence override(实际 skip 因 SF-105)
- [x] T2.3 `configs/ppo/smoke_full.toml` 新增 — extends smoke.toml +
  cadence override(实际 skip 因 SF-105)
- [x] T2.4 `configs/cfr/smoke_full.toml` 新增 — extends smoke.toml +
  cadence override(实际 skip 因 SF-105)
- [x] T2.5 `configs/bc/smoke_full.toml` 新增 — extends smoke.toml +
  cadence override(实际 skip 因 SF-105)
- [x] T2.6 `training/tests/test_dmc_smoke_full.py` 新增 ~20 LOC — 1 test
  via shared template
- [x] T2.7 `training/tests/test_az_smoke_full.py` 新增 ~20 LOC — 1 test +
  `pytest.skip` 标记 pre-existing bug
- [x] T2.8 `training/tests/test_ppo_smoke_full.py` 新增 ~20 LOC — 1 test +
  `pytest.skip`
- [x] T2.9 `training/tests/test_cfr_smoke_full.py` 新增 ~20 LOC — 1 test +
  `pytest.skip`
- [x] T2.10 `training/tests/test_bc_smoke_full.py` 新增 ~20 LOC — 1 test +
  `pytest.skip`(缺 NPZ dataset)

## Phase 3 — Verify gates(hard)

- [x] T3.1 `pytest --collect-only training/tests/` test count 与 ship 前
  比对 — smoke_full **不被收集**(addopts 默认 exclude)。baseline=1006,
  post=1006(smoke_full files unaffected to default sweep)
- [x] T3.2 `pytest -m smoke_full training/tests/test_dmc_smoke_full.py` —
  DMC end-to-end pass(包含 100+ step train + ckpt save + resume)
- [x] T3.3 `pytest -m smoke_full training/tests/` 5 个全 collect — 4 skip
  + 1 pass(DMC),0 fail
- [x] T3.4 默认 `pytest training/tests/ -q` 跑通 — smoke_full 文件不被
  collect(addopts 排除),baseline 测试 0 regression
- [x] T3.5 Line limit 校验:`smoke_full_template.py < 300` / 各 test
  文件 < 300 / configs/<paradigm>/smoke_full.toml < 300
- [x] T3.6 `tools/_meta/check_openspec_indices.py --staged` 通过(若适用)

## Out of scope(此 change 不做,follow-up)

- 修复 AZ `card_pool_spec` dict 类型 bug(`training/paradigms/az/collector.py:72`
  应 wrap `resolve_pool_refs` → `make_pool_spec`)— 新 follow-up change
  `az-pool-spec-type-fix`
- 修复 PPO `card_pool=None` 处理(`training/paradigms/ppo/_rollout.py:130`
  `list(None)` 失败)— 新 follow-up `ppo-rollout-card-pool-none-fix`
- 修复 CFR `max_game_steps=30` 在 smoke scenario 不足以完一 traversal —
  bump 到 200+ 或检查 traversal terminate 逻辑;`cfr-smoke-max-steps-fix`
- BC smoke_full 自动 gen NPZ dataset fixture — `bc-smoke-dataset-fixture`
