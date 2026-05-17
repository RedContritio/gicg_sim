# ppo-buffer-clear-orchestration — tasks

`StepPlan.clear_buffer_after_train: bool` field + pipeline driver post-train
conditional clear + PPO step_schedule set true。其它 4 paradigm 默认 False
不动。完整 propose + impl + verify + archive 单 session。

**注:** Verify 暴露 third-deeper cascade `paradigm-head-kinds-deterministic-iter`
阻塞 smoke_full 真正 PASS;本 change 完成 buffer-clear 部分,test 仍 SKIPPED
但 skip reason 指向新 cascade(详 proposal.md "Discovery during verify" 段)。

## T1 — protocols.py StepPlan field

- [x] T1.1 `training/core/protocols.py:92-101` `StepPlan` dataclass 末尾加
  `clear_buffer_after_train: bool = False` field(位置 `advance_step` 之后,
  保持 trailing-default 顺序)
- [x] T1.2 docstring 更新 — "on-policy paradigm 显式声明 buffer.clear epilogue"

## T2 — pipeline.py post-train epilogue

- [x] T2.1 `training/core/pipeline.py` train block 之后加:
  ```python
  if plan.clear_buffer_after_train:
      buffer.clear()
  ```
  位置:`logger.add_scalar('train/loss', ...)` 之后,`if plan.eval and ...`
  之前;与 `if plan.train` 独立 if(honor flag 无论 train block 是否真跑)

## T3 — PPO paradigm.py step_schedule set field

- [x] T3.1 `training/paradigms/ppo/paradigm.py:141-149` steady path
  `StepPlan(...)` 加 `clear_buffer_after_train=True`(总 8 字段)
- [x] T3.2 `step_schedule` docstring 更新:on-policy clear 显式声明已 wired

## T4 — Test docstring update + skip reason refined

- [x] T4.1 `training/tests/test_ppo_smoke_full.py`:
  - **计划** unskip,实际 verify 后保留 `@pytest.mark.skip` decorator
  - 更新 skip reason:从 "RolloutBuffer overflow" → "Adam optimizer.state_dict
    resume desync via non-deterministic head_kinds set iteration"
  - 更新 module docstring "STATUS" 段:加 cascade #2(本 change)+ #3
    (新 cascade `paradigm-head-kinds-deterministic-iter`)

## T5 — Spec deltas

- [x] T5.1 `openspec/changes/ppo-buffer-clear-orchestration/specs/training-architecture/spec.md`
  ADD 1 SHALL(on-policy paradigm 必须声明 buffer.clear epilogue via
  StepPlan flag,driver 必须 honor 此 flag)
- [x] T5.2 不动 `paradigm-ppo/spec.md`(§ P4.1 already SHALL)

## T6 — Verify

- [x] T6.1 `pytest training/tests/test_ppo_smoke_full.py -v -m smoke_full --tb=short`
  SKIPPED(新 reason 指向 head_kinds cascade)
- [x] T6.2 **手 verify**:`tools.run --max-steps 5` 跑通(原 baseline 在 step
  1-2 必 raise overflow)→ buffer-clear fix 真生效
- [x] T6.3 **额外手 verify**:50-iter full run train + saves 3+ ckpts 成功;
  resume 路径暴露 third-deeper cascade(证 buffer-clear 完整)
- [x] T6.4 `pytest training/tests/test_ppo_*.py -v --tb=short` no regression
  (40 passed)
- [x] T6.5 `pytest training/tests/test_{az,bc,cfr,dmc}_*.py -v --tb=short` no
  regression(404 passed,3 skipped,4 deselected)
- [x] T6.6 `tools._meta.check_openspec_indices` pass
- [x] T6.7 `tools._meta.check_line_limits` pass

## T7 — Archive

- [x] T7.1 Update `design.md` retrospective(≤ 200 行 + 5 sections per
  archive-workflow.md Step 4)
- [x] T7.2 tasks.md `[x]`
- [x] T7.3 Spec delta merge(T5.1 SHALL 合入 `openspec/specs/training-architecture/protocols.md` § 4)
- [x] T7.4 git mv changes/ppo-buffer-clear-orchestration → changes/archive/
- [x] T7.5 Single commit `openspec archive: ppo-buffer-clear-orchestration`

## Out of scope(发现自 verify;NEW follow-up queued)

- **`paradigm-head-kinds-deterministic-iter`** (NEW follow-up):
  `training/core/network/actor_critic.py:258` `for kind in head_kinds:` 直接
  迭代 set(non-deterministic across process via PYTHONHASHSEED)→ ckpt save
  时 process A 的 net.parameters() order ≠ resume process B 的 order →
  optimizer.state_dict 的 `state` keys(param positional id)错位 → Adam
  exp_avg / grad shape 错配 raise。5 paradigm 中所有 multi-head paradigm
  affected(PPO/AZ/CFR;DMC 单 head 不 affected,已 verified DMC smoke_full
  PASS)。1-line code fix(`for kind in sorted(head_kinds):`)+ spec
  invariant("head_kinds iteration SHALL be deterministic")。跨 capability
  network-architecture / 5 paradigm 共享 backbone,**不属于本 change scope**。

## Estimated workload(actual)

| Item | LOC |
|---|---|
| `protocols.py` StepPlan +1 field + docstring | +9 / -1 |
| `pipeline.py` post-train epilogue +注释 | +6 / -0 |
| `ppo/paradigm.py` step_schedule +1 field + docstring | +8 / -0 |
| `test_ppo_smoke_full.py` docstring 更新 + skip reason refined | +30 / -18 |
| Spec delta(`training-architecture/protocols.md`)+1 SHALL | +13 / -0 |
| OpenSpec docs(proposal/tasks/design)| +330 |
| **Total** | **~395 LOC(66 code/spec + 330 docs)** |
