# ppo-rollout-card-pool-none-fix — tasks

1-line fix + 同 broken pattern siblings(共 3 处:_rollout.py 两行 + _async.py
一行)。**注:** 原计划 unskip test 但实际 implementation 发现 smoke_full 仍被
新的、更深的 bug 阻塞(buffer.clear 未在 pipeline driver 中 wire),详 design.md。

## T1 — Fix card_pool + obs_mask broken `list(getattr) or` patterns

- [x] T1.1 `training/paradigms/ppo/_rollout.py:130` 改 `list(getattr(scen, 'card_pool', ())) or []` → `list(getattr(scen, 'card_pool', None) or ())`
- [x] T1.2 `training/paradigms/ppo/_rollout.py:131` 同样模式 sibling(`obs_mask`)改 `list(getattr(scen, 'obs_mask', ())) or None` → `list(getattr(scen, 'obs_mask', None) or ()) or None`
- [x] T1.3 `training/paradigms/ppo/_async.py:59` 同 `card_pool` broken pattern 修复(grep 全 repo 确认共 3 处,均为 PPO,均为同根因)

## T2 — 更新 test docstring(skip 保留 + 更新 reason)

- [x] T2.1 `training/tests/test_ppo_smoke_full.py`:
  - 保留 `@pytest.mark.skip(...)` decorator(因新 blocker)
  - 改 skip reason:从 "card_pool TypeError" → "RolloutBuffer overflow (pipeline driver 无 buffer.clear orchestration)"
  - 改 module docstring "STATUS" 段反映新现状

## T3 — Verify

- [x] T3.1 `pytest training/tests/test_ppo_smoke_full.py -v -m smoke_full --tb=short` 确认 SKIPPED(新 reason)
- [x] T3.2 直接 run driver smoke_full subprocess 确认原 card_pool/obs_mask TypeError 不再 fire,新 trace 是 RolloutBuffer overflow(证 fix 真生效)
- [x] T3.3 `pytest training/tests/test_ppo_*.py -v --tb=short` no regression
- [x] T3.4 `tools._meta.check_openspec_indices` pass
- [x] T3.5 `tools._meta.check_line_limits` pass

## T4 — Archive

- [x] T4.1 Update `design.md` retrospective(≤ 200 行 + 5 sections per archive-workflow.md Step 4)
- [x] T4.2 tasks.md `[x]`
- [x] T4.3 git mv changes/ppo-rollout-card-pool-none-fix → changes/archive/...
- [x] T4.4 Single commit `openspec archive: ppo-rollout-card-pool-none-fix`

## Out of scope(发现自 verify;new follow-up queued)

- **`ppo-buffer-clear-orchestration`** (NEW follow-up):pipeline driver
  (`training/core/pipeline.py`) 缺 on-policy paradigm 的 `buffer.clear()` 调用,
  导致 PPO 第 2 iter `collect` 必 overflow(`RolloutBuffer.push: over
  capacity`)。Buffer protocol 注释(`training/core/protocols.py:209`)
  显式预期此调用("clear() called by on-policy paradigms (PPO) per iter")
  但 wire 未落地。需 paradigm hook 或 StepPlan flag,跨 protocols + pipeline
  + PPO paradigm,~30-60 LOC,**不属于本 change scope**(本 change 是
  card_pool/obs_mask 1-line 类 bug)。

## Estimated workload(actual)

| Item | LOC |
|---|---|
| `_rollout.py:130` card_pool | +1 / -1 |
| `_rollout.py:131` obs_mask | +1 / -1 |
| `_async.py:59` card_pool | +1 / -1 |
| `test_ppo_smoke_full.py` docstring + skip reason 更新 | +20 / -10 |
| OpenSpec docs(proposal/tasks/design) | +250 |
| **Total** | **~275 LOC(13 code + 250 docs)** |
