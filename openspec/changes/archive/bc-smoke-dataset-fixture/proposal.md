# bc-smoke-dataset-fixture — 闭 BC smoke_full skip

**Status:** Active change(implementation pending)
**Date opened:** 2026-05-17
**Supersedes:** None
**Affected specs:** None(纯 test infra,无 SHALL change)

## Why

`paradigm-smoke-full-tier` (#6) ship 之后,5 paradigm smoke_full 测试中 BC 是 4 个 skip 之一,原因 per SF-105:

> BC paradigm 需 NPZ expert dataset(`paradigm.dataset_path`),smoke 没 fixture 生成。

`training/tests/test_bc_smoke_full.py:42` 用 `@pytest.mark.skip(reason='BC smoke_full blocked by missing NPZ dataset fixture ...')` 标记,因:

- `training/paradigms/bc/collector.py:42` `DatasetCollector.__init__` raises `ValueError('DatasetCollector: dataset_path must be non-empty')` 当 path 为空
- `configs/bc/smoke.toml` `paradigm.dataset_path = ""`(production datasets GB-sized,gitignored;repo 不 ship NPZ)
- 必须 test-time auto-gen NPZ + 注入 dataset_path

#6 SF-105 explicitly defer 此修复:**"generating a tiny on-the-fly NPZ fixture (via tools/dataset/gen_bc.py) is OUT of scope for this change. Follow-up: bc-smoke-dataset-fixture"**。

本 change 闭此 follow-up。

## What

1. **Extend** `training/tests/smoke_full_template.py::run_paradigm_train_via_driver`:加 optional `extra_overrides: list[str] | None = None` kwarg,backward-compatible(default None → 行为不变)。`--override` flag 可重复,template 把 user-supplied list 拼到 subprocess cmd。
2. **Add** `_gen_bc_npz_for_smoke(tmp_path: Path) -> Path` helper in `training/tests/test_bc_smoke_full.py`:
   - 构造最小 gen_bc cfg(沿用 `configs/bc/smoke.toml` scenario:赤蝶 mirror / pool=`v_legacy, test_basic` / `target_decisions=20, max_games=5`,与 `tools/dataset/tests/test_gen_bc_schema.py::test_collect_produces_az_shape_only` 同款 tiny smoke)
   - In-process call `tools.dataset.gen_bc.collect(cfg)`(不 subprocess,~2 s wall)
   - `np.savez_compressed(tmp_path / 'dataset.npz', **fields)`
   - return path
3. **Remove** `@pytest.mark.skip` decorator + pass `extra_overrides=[f'paradigm.bc.dataset_path={npz_path}']` 到 driver call。
4. **Update** docstring 删 SKIPPED 段、更新 STATUS line。

## Affected specs

无 spec delta(纯 test infrastructure,no SHALL change)。

## Out of scope

- 其它 3 个 smoke_full skip(az-pool-spec-type-fix / ppo-rollout-card-pool-none-fix / cfr-driver-buffer-multihead-fix)分别独立 follow-up
- BC dataset gen performance optimization(本 change 沿用 existing gen_bc smoke pattern,~2 s wall acceptable)
- gen_bc cfg schema 变更(沿用 existing `_KNOWN_CFG_KEYS`)

## Verification

- `pytest -m smoke_full training/tests/test_bc_smoke_full.py -v` PASS
- `pytest training/tests/test_bc*.py -v` 无 regression(BC 其它 smoke / hard target / paradigm test 不受影响)
- `tools._meta.check_openspec_indices` 无 violation
- `tools._meta.check_line_limits` 无 violation
