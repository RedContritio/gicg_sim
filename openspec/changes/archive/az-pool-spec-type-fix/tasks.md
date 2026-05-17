# az-pool-spec-type-fix — tasks

Single-day follow-up fix(~15 LOC code + spec delta + test unskip)。

## T1 — Fix 3 violation sites

- [x] T1.1 `training/paradigms/az/collector.py:72` — `AZSelfPlayCollector.__init__`:
  wrap `resolve_pool_refs(cfg.scenario)` with `make_pool_spec(cfg.scenario, ...)`;
  import `make_pool_spec` 加到 line 19 既有 `from .pool_spec import resolve_pool_refs`
- [x] T1.2 `training/paradigms/az/collector.py:172` — `_az_build_policy`(async actor 工厂):
  同上 wrap
- [x] T1.3 `training/paradigms/az/paradigm.py:152` — `AZParadigm.make_episode_policy`:
  同上 wrap;import 加 `make_pool_spec`

## T2 — Bundled fix:AZNetwork.game_start drop return value

(发现自 smoke_full baseline verify after T1 ship — 同一 smoke_full unblocking path 下一 sequential blocker)

- [x] T2.1 `training/paradigms/az/network.py:280-281` `AZNetwork.game_start`:
  add `return` + annotate `-> dict`(与 `AgentBase.game_start` contract 一致)
  + 内联 comment 说明 bundled 理由
- [x] T2.2 verify:smoke_full subprocess 不再触发 `'NoneType' object has no
  attribute 'keys'` at buffer push

## T3 — Test skip-reason rewrite(原计划 unskip → 改为 partial unblock)

- [x] T3.1 `training/tests/test_az_smoke_full.py` rewrite docstring + skip reason:
  Train-phase(A1.6.1+.2)PASSES post 本 change ship(`final: step=30
  frames=1025 episodes=30 train_steps=29 wall_s=25.2`),Resume-phase(A1.6.3)
  仍 fail by pre-existing deeper AZ ckpt-resume optimizer shape mismatch
  bug → keep `@pytest.mark.skip` 但 reason 切到新 follow-up id
  **`az-resume-shape-fix`**。
- [x] T3.2 verify:`pytest test_az_smoke_full.py -m smoke_full --tb=long`
  显示 train subprocess A1.6.1+.2 PASS,Resume subprocess fail at adam.py:547
  `output with shape [1, 64] doesn't match the broadcast shape [1832, 64]`。
  本 change ship 不解锁 unskip,但 train-phase 已可独立 verify(per cfg
  `--max-steps` 切短 OR 单独 unit test)。

## T4 — Spec delta merge

- [x] T4.1 `openspec/changes/az-pool-spec-type-fix/specs/paradigm-az/spec.md` 写 A5.4 ADD delta
- [x] T4.2 archive 时 merge 入 `openspec/specs/paradigm-az/spec.md` A5 section
  (A5.1-A5.3 后追加 A5.4 编号 = 15 invariant);Status section +Revised entry

## T5 — Verification

- [x] T5.1 `pytest training/tests/test_az_*.py training/tests/test_determinize.py`(without smoke_full marker):72/72 baseline pass(无 regression);smoke_full test 仍 skip,新 reason 已切到 `az-resume-shape-fix`
- [x] T5.2 Full sweep `pytest -n 4 training/tests/`(ignoring known-bad eval_service/cfr_worker/parallel_trainer/inference_server per memory):995 passed / 3 skipped / 0 failed
- [x] T5.3 `tools/_meta/check_openspec_indices` pass
- [x] T5.4 `tools/_meta/check_line_limits` pass(paradigm-az/spec.md 当前 158 行 + A5.4 ≤ 175 → 仍 < 300)

## T6 — Archive

- [x] T6.1 Archive design.md retrospective(verdict + tradeoffs + surprises + spec delta summary,≤ 200 行)
- [x] T6.2 git mv `openspec/changes/az-pool-spec-type-fix/` → `openspec/changes/archive/`
- [x] T6.3 Single commit per archive-workflow.md SOP

## Estimated workload(actual)

| Item | LOC |
|---|---|
| `paradigms/az/collector.py` 2 sites + import + comment | +9 / -2 |
| `paradigms/az/paradigm.py` 1 site + import + comment | +4 / -1 |
| `paradigms/az/network.py` bundled game_start fix | +6 / -1 |
| `tests/test_az_smoke_full.py` unskip + docstring rewrite | +5 / -18 |
| Spec delta + retrospective design | +130 |
| **Total** | **~155 LOC(25 code + 130 docs)** |
