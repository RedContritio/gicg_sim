# bc-smoke-dataset-fixture — Design Retrospective

> Archive-time retrospective(≤ 200 lines per archive cap)。本 change 是
> 轻量 test-infra follow-up(~140 LOC test code,0 production code change,
> 0 spec delta);本文档完整记录决策、验证、与 discovered bug。

## Verdict

**部分成功** — BC smoke_full 不再 `pytest.skip`(SF-105 fixture blocker 闭),
ckpt save / resume codepath 端到端跑通。但 fixture work 暴露 1 个 **NEW
pre-existing pipeline bug**:`training/core/pipeline.py:83` collect gate
`if plan.collect and plan.n_episodes > 0` 阻塞 BC 的 `n_episodes=0` plan,
导致 buffer 空 → train_steps=0/frames=0 → BC 网络 actually never trains。

Test passes A1.6.2 file-existence contract(4 ckpt files + latest.pt +
metrics.jsonl + resume gain 1 new ckpt at step=130),但 **不 validate
BC loss convergence**。Follow-up needed:`bc-pipeline-collect-gate-fix`
(单行 fix — relax gate to `if plan.collect`,let collector itself decide
how much to collect)。

实施单 day / 5 task all done / `pytest -m smoke_full
training/tests/test_bc_smoke_full.py -v` PASS / `pytest training/tests/
test_bc*.py` 29/29 pass / full sweep 1010 passed / 3 skipped(pre-existing)
/ 0 failed。

## What we built

- `training/tests/smoke_full_template.py` — extend `run_paradigm_train_via_driver`
  + `resume_and_continue` 加 `extra_overrides: list[str] | None = None` kwarg
  (default None → 行为不变,backward-compatible)。subprocess cmd 用 list
  loop `for ov in extra_overrides or []: cmd.extend(['--override', ov])`
  保证 each override 走单独 `--override` flag(`tools.run` argparse 用
  `action='append'`)
- `training/tests/test_bc_smoke_full.py` — 重写:
  - 删 `@pytest.mark.skip` decorator + 删 SKIPPED docstring 段
  - 新加 `_gen_bc_npz_for_smoke(tmp_path: Path) -> Path` helper:用
    `tools.dataset.gen_bc.collect(cfg)` in-process(沿用
    `test_gen_bc_schema::test_collect_produces_az_shape_only` smoke
    pattern,~1.3 s wall),write NPZ via `np.savez_compressed`,return path
  - cfg dict 用 BC smoke scenario(赤蝶 mirror / `pool=['v_legacy',
    'test_basic']` / `target_decisions=20, max_games=5` / `teacher='F1-D2'`)
  - test 主体:`fixture/` + `artifacts/` subdir 分开(disjoint),inject
    NPZ path via `extra_overrides=[f'paradigm.bc.dataset_path={npz}']`
  - resume bump `paradigm.bc.n_epochs=130`(原 cfg 100;不 bump resume
    立即退出,详 Tradeoffs D2)
  - docstring 加 KNOWN CONCERN 段记录 pipeline.py collect gate bug

## Tradeoffs revisited

- **In-process gen_bc vs subprocess**(D1):预期 + 实际 SELECTED in-process ✓
  — sister test 已示范,~1.3 s wall in-process vs ~3-5 s subprocess
  (extra Python boot + libgicg load),smoke_full budget 紧。
- **Fixture in test file vs conftest.py**(D2):预期 + 实际 SELECTED 局部
  helper ✓ — 单一 caller,BC-specific,scope 局部化清晰;test 文件 110 行
  << 500 行 cap。
- **gen_bc cfg minimums**(D3):预期 `target_decisions=20`,实际 20 ✓ —
  覆盖 batch_size=8 + held_out_frac=0.1 split,~18 train decisions / 8 =
  2 batches/epoch。`pool=['v_legacy', 'test_basic']`(预期 `test_basic`
  only,实际改 dual pool 因 `赤蝶` lives in v_legacy)。
- **extra_overrides on template vs only in test**(D4):预期 template ✓
  — 未来其它 paradigm follow-up 也可能需要 paradigm-specific override
  (PPO/CFR fix 完后 follow-up),单一 extension point。
- **NEW DECISION resume bump n_epochs**(D6,not in original design):
  实际发现 BC 不同于 DMC — DMC terminus 是 `total_frames` 动态,resume
  state.step 自然超过 existing ckpt;BC terminus 是 fixed `n_epochs`,
  resume from lex-first `ckpt_100`(lex sort 把 100 排前面)时 loop 立即
  退出,final-save 同 step → overwrite → 0 new ckpt → A1.6.3 fail。
  workaround:resume 时 inject `paradigm.bc.n_epochs=130` override(BC-
  specific 知识 — 其它 paradigm 不需要)。

## Surprises

- **DISCOVERED pipeline collect-gate bug**(`training/core/pipeline.py:83`):
  fixture work 终于让 BC smoke_full 跑过 collection 阶段,暴露
  pre-existing bug:`if plan.collect and plan.n_episodes > 0` 把 BC 的
  `n_episodes=0` plan 拒掉,collector 永远 NOT 调用 → buffer 空 →
  train batches 全 `len(buffer) < batch_size` skip → `train_steps=0,
  frames=0`。BC `state.step`(epoch counter)仍正常 advance,ckpt save
  cadence triggers,网络以 random init 被 ckpt save → 测试 file 存在性
  contract 满足,但 NO TRAINING。这是 SF-105 当时 unknown 的第二层 bug,
  本 change 因严格 scope 不修(per user direction:`若 smoke_full 跑过
  但暴露其它 BC bug → DONE_WITH_CONCERNS`)。Test docstring 加 KNOWN
  CONCERN 段使可见,recommend follow-up `bc-pipeline-collect-gate-fix`。

- **DMC test 也依赖 lex sort + dynamic terminus quirk pass**(意外):
  调研 DMC smoke_full 为啥 pass 时发现 — DMC `ckpts[0]`(lex sort)= 
  `ckpt_120.pt`(`1<3<6<9` lex);resume from 120 时 DMC step_schedule
  仍 advance(`total_frames=2500` 已达 但 state.step 继续走 4 个 step
  to step=190),`finally` ckpt_mgr.save 写 ckpt_190(新 step 号)→ 5→6
  ckpts gain。BC 没有这个动态 terminus 头空间,所以需要 D6 的 n_epochs
  bump。

- **20 decisions 跑 5 局 mirror 比预期慢**(LOW):预期 ~1.3 s(同
  `test_gen_bc_schema` smoke 同 cfg),实际 ~1.0 s — 因 BC test cfg
  `card_pool=[]`(no cards)更快;DSL 仍 ~600 ms cold boot,跑 5 局
  ~400 ms。整 smoke_full 测试(fixture + train + resume)总 ~2.5 s wall。

## Spec delta summary

本 change **不修订任何 capability spec**(纯 test infrastructure,no SHALL
change)。

Cross-references:
- 闭 `paradigm-smoke-full-tier` [SF-105] 4 follow-up 之一(BC fixture)
  — 删 `test_bc_smoke_full.py::test_bc_smoke_full` 的 `@pytest.mark.skip`
- A1.6.2 file-existence contract 满足(4+ ckpt files / latest.pt /
  metrics.jsonl)
- A1.6.3 resume-gain-new-ckpt 满足(经 D6 workaround:resume bump
  n_epochs)
- **NOT 闭** loss convergence validation(被新 discovered pipeline bug
  blocked,需 follow-up)

## DECISIONS index

本 change 无独立 DECISIONS file(轻量 follow-up,所有 design 决策记录在
本 retrospective design.md)。Cross-reference:

- `paradigm-smoke-full-tier` [SF-105] BC defer → **fixture portion
  closed** by this change(skip 删,test runs to completion)
- `paradigm-smoke-full-tier` [SF-105] BC defer → **pipeline path
  portion remains open** — discovered NEW bug,需 `bc-pipeline-collect-
  gate-fix` follow-up(out of this change scope per CLAUDE.md 范围扩张
  protocol)
- `paradigm-smoke-full-tier` [A1.6.2 / A1.6.3] 满足
