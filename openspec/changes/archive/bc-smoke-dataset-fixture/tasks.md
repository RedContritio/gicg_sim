# bc-smoke-dataset-fixture — tasks

Lightweight follow-up(~80 LOC test infra,0 production code change)。

## T1 — Template extension

- [x] T1.1 `training/tests/smoke_full_template.py::run_paradigm_train_via_driver`:add optional `extra_overrides: list[str] | None = None` kwarg(default None → 行为不变,backward-compatible)
- [x] T1.2 `training/tests/smoke_full_template.py::resume_and_continue`:同样 add `extra_overrides` kwarg(resume 也需要 re-supply dataset_path / n_epochs override 等 paradigm-specific overrides,因 cfg load 是 from-disk)
- [x] T1.3 update template docstring(noting `extra_overrides` for paradigm-specific cfg injection like BC dataset_path)

## T2 — BC fixture helper

- [x] T2.1 `training/tests/test_bc_smoke_full.py`:add `_gen_bc_npz_for_smoke(tmp_path)` helper invoking `tools.dataset.gen_bc.collect()` in-process,write NPZ via `np.savez_compressed`
- [x] T2.2 cfg dict 用 BC smoke scenario(赤蝶 mirror / `card_pool=[]` / `target_decisions=20, max_games=5` / `teacher='F1-D2'` / `pool=['v_legacy', 'test_basic']` 同 `test_gen_bc_schema` smoke pattern)
- [x] T2.3 remove `@pytest.mark.skip` decorator + 改 docstring 删 SKIPPED 段
- [x] T2.4 inject NPZ path via `extra_overrides=['paradigm.bc.dataset_path=<npz_path>']`
- [x] T2.5 resume 时 bump `paradigm.bc.n_epochs=130`(BC terminus 是 fixed n_epochs,resume from ckpt_100 不 bump 会立即退出 → final-save 同 step → overwrite → 0 new ckpt → A1.6.3 assertion fail。bump 给 resumed run room 走 100→130 阶段产新 ckpt_130)
- [x] T2.6 docstring 加 KNOWN CONCERN 段记录 discovered pipeline bug(`pipeline.py:83` collect gate `n_episodes > 0` 阻塞 BC 数据 push → train_steps=0/frames=0,需独立 follow-up 修)

## T3 — Verification

- [x] T3.1 `pytest -m smoke_full training/tests/test_bc_smoke_full.py -v --tb=short` PASS(BC smoke_full 不再 skip)
- [x] T3.2 `pytest training/tests/test_bc_paradigm.py test_bc_smoke.py test_bc_hard_target.py -v` 29/29 pass(BC 其它 test 无 regression)
- [x] T3.3 `pytest -n 4 training/tests/ tools/dataset/tests/` 1010 passed / 3 skipped(pre-existing per memory)/ 0 failed
- [x] T3.4 `pytest -m smoke training/tests/` 5/5 pass(其它 paradigm smoke 不受 template extension 影响 — backward-compatible default kwarg)
- [x] T3.5 `tools._meta.check_openspec_indices` 0 violation
- [x] T3.6 `tools._meta.check_line_limits` 9 pre-existing violators(grandfathered),新文件无 violation
- [x] T3.7 `ruff format --check` 通过

## T4 — Archive

- [x] T4.1 update `design.md` 为 retrospective(≤ 200 行,5 sections per archive workflow § 2.4)
- [x] T4.2 verify all T1/T2/T3 boxes `[x]`
- [x] T4.3 `tools._meta.openspec_archive --change-id bc-smoke-dataset-fixture --no-commit`(no `--specs-merged` 因 no specs/)
- [x] T4.4 single commit with `openspec archive: bc-smoke-dataset-fixture` message

## Estimated workload(actual)

| Item | LOC |
|---|---|
| smoke_full_template.py extension(`extra_overrides` on 2 helpers) | +30 / -2 |
| test_bc_smoke_full.py fixture + skip removal + concern doc | +110 / -50 |
| OpenSpec propose docs(proposal/tasks/design) | +250 |
| **Total** | **~390 LOC(~140 code + ~250 docs)** |
