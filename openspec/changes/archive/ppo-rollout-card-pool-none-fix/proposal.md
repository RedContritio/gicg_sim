# ppo-rollout-card-pool-none-fix — PPO _rollout.py + _async.py 修 card_pool/obs_mask=None TypeError

**Status:** Active change(propose 阶段,即将 impl + archive in single session)
**Date opened:** 2026-05-17
**Supersedes:** None
**Affected specs:**
- None(纯 bug fix,无 SHALL 变化;若加 None-handling invariant 见下方"考虑过未加")

## Why

`paradigm-smoke-full-tier` (#6) baseline sweep 暴露 PPO smoke_full 当 scenario
`card_pool = None`(smoke scenarios default)时 `TypeError: 'NoneType' object
is not iterable`,源自:

```python
# training/paradigms/ppo/_rollout.py:130
card_pool = list(getattr(scen, 'card_pool', ())) or []
```

`getattr(scen, 'card_pool', ())` 当 attribute 存在但 value 为 `None`
(paradigm config dataclass `card_pool: Optional[list] = None`)时返回 `None`,
**default `()` 被 ignored**(getattr 第三参数只在 attr 不存在时 fallback)。
`list(None)` 立即 raise,`or []` fallback 永不 evaluate。

同样 broken pattern 在 `_rollout.py:131`(obs_mask,sibling)+ `_async.py:59`
(card_pool)也有(grep 全 repo 共 3 处,均为 PPO)。

Per #6 SF-105,该 paradigm bug OUT of #6 scope,挂 follow-up
`ppo-rollout-card-pool-none-fix`,即本 change。

## What

1. `training/paradigms/ppo/_rollout.py:130`:
   ```python
   - card_pool = list(getattr(scen, 'card_pool', ())) or []
   + card_pool = list(getattr(scen, 'card_pool', None) or ())
   ```
   语义:显式 `None` default + falsy coalesce **在 `list()` 之前** evaluate。
   None / 缺失 / 空 list 三者统一为空 iter。
2. `training/paradigms/ppo/_rollout.py:131`(同根因 sibling):
   ```python
   - obs_mask = list(getattr(scen, 'obs_mask', ())) or None
   + obs_mask = list(getattr(scen, 'obs_mask', None) or ()) or None
   ```
   `obs_mask` 下游期望 None(非空 list)表示"无 mask",故 `or None` 保留。
3. `training/paradigms/ppo/_async.py:59`:同 `card_pool` broken pattern 同样修复
4. `training/tests/test_ppo_smoke_full.py`:**计划** unskip,实际 verify 后改为
   保留 skip 但更新 reason(详 "Discovery" 段)

Mirror AZ/DMC/BC None handling pattern(per 任务 spec)。

## Discovery during verify(scope-relevant)

原任务 spec 假定 1-line `card_pool` fix → smoke_full PASS,unskip test 即可。
实际 implementation 修完 3 处 broken pattern 后 verify 发现 smoke_full 仍
fail,新 trace 是 **不同 root cause**:

```
RuntimeError: RolloutBuffer.push: over capacity=500;
clear() between iters
```

PPO `Buffer` protocol(`training/core/protocols.py:209`)显式预期
"`clear()` called by on-policy paradigms (PPO) per iter",但新 pipeline driver
(`training/core/pipeline.py`)从未 wire 此调用 — 第 2 outer iter `collect`
push 进满 buffer 必 raise。

**判断:** 此 bug 是 distinct root cause,跨 protocols + pipeline + paradigm,
~30-60 LOC,**不属于本 change scope**(本 change 是 card_pool/obs_mask 1-line
类 bug per 任务 spec wording "1-line fix")。本 change 修原 bug + 更新 test
skip reason 指向新 follow-up `ppo-buffer-clear-orchestration`(NEW,见
tasks.md "Out of scope" 段)。

## Affected specs

- None(SHALL 无变化)— 该 bug 是 implementation defect,非 contract gap。
- 考虑过加 `paradigm-ppo/spec.md` "None 输入 fallback 必空 iter" SHALL,但:
  - **过度规约**:Python 1-line idiom,加 SHALL 反而抬高维护成本
  - **已被覆盖**:`training-architecture` "scenario fields nullable 处理"
    隐含约束(N1.2 cfg dataclass + factory 默认)
  - **测试代偿**:future smoke_full PASS(待 `ppo-buffer-clear-orchestration`
    ship 后)即 effective guard

## Out of scope

- `ppo-buffer-clear-orchestration` follow-up(详 Discovery 段)— 阻塞
  smoke_full PASS 的真正剩余 blocker,跨 protocols/pipeline,需独立 change
- 其它 paradigm 类似 `getattr or` 模式 audit(grep 已确认仅 PPO 3 处)
- PPO 算法 refactor(本 change 纯 bug fix)
- 5 paradigm 共享 scenario 工具函数提取(若未来加更多 getattr 模式可考虑)

## Acceptance

1. `pytest training/tests/test_ppo_smoke_full.py -v -m smoke_full` 仍 SKIPPED
   (新 reason 反映 buffer-clear blocker;原 card_pool reason 消失)
2. **手 verify**:直接 run driver subprocess,trace 不再出现
   `list(None) TypeError`,改出现 `RolloutBuffer overflow`(证 3 处 fix 真生效)
3. `pytest training/tests/test_ppo_*.py` 全 pass,no regression
4. PPO smoke_full 4/5 → 仍 4/5 skipped 但 blocker 重命名(参 memory
   `project_smoke_full_discovered_bugs_2026_05_17`,follow-up queue 加 1 项)

## Verification

```bash
.venv/bin/python -m pytest training/tests/test_ppo_smoke_full.py -v -m smoke_full --tb=short
# 期望:SKIPPED,reason 含 "RolloutBuffer overflow"

.venv/bin/python -m tools.run configs/ppo/smoke_full.toml --override checkpoint.artifacts_root=/tmp/test_x 2>&1 | tail -10
# 期望:RuntimeError 而非 TypeError;证 card_pool/obs_mask fix 生效

.venv/bin/python -m pytest training/tests/test_ppo_*.py -v --tb=short
# 期望:no regression

.venv/bin/python -m tools._meta.check_openspec_indices
.venv/bin/python -m tools._meta.check_line_limits
```

## Cross-references

- `paradigm-smoke-full-tier` #6 SF-105:四 paradigm 跳过 + follow-up changes
  queued(本 change 是其中之一)
- memory `project_smoke_full_discovered_bugs_2026_05_17`:四 bug + queue 列表;
  本 change ship 后 queue 加 5th(`ppo-buffer-clear-orchestration`)
- AZ scenario None handling 对照点:
  `training/paradigms/az/inference_worker.py:104` 处直接 pass 不再 wrap;
  `training/paradigms/dmc/_run_config.py:132` 直接传 list literal
