# ppo-rollout-card-pool-none-fix — Design Retrospective

> Archive-time retrospective(≤ 200 行 per archive-workflow.md Step 4)。本 change
> 是轻量 follow-up(~13 LOC code + ~250 LOC docs),无 design/ subdir 拆分必要;
> 本文档完整记录 verdict + tradeoff + surprise + spec delta。

## Verdict

**部分成功** — 任务 spec 描述的 `card_pool=None TypeError` bug **真正修复**
(`_rollout.py:130` + sibling `_rollout.py:131` obs_mask + 同 broken pattern
`_async.py:59` 共 3 处全 fix)。手动 verify 直接 run driver subprocess 确认
原 trace `list(None) → TypeError` 不再 fire。

但 **smoke_full 仍未 PASS** — verify 暴露 distinct deeper bug:
`RolloutBuffer.push: over capacity=500; clear() between iters`。
PPO `Buffer` protocol 显式预期 on-policy `clear()` per iter,但新 pipeline
driver(`training/core/pipeline.py`)从未 wire 此调用,第 2 outer iter
`collect` push 进满 buffer 必 raise。此 bug 跨 protocols + pipeline + paradigm
hook,~30-60 LOC,**非 1-line 类**(任务 spec 明示"1-line fix"scope),拆为
NEW follow-up `ppo-buffer-clear-orchestration`。

实施 ~13 LOC code + 250 LOC docs / 78/78 PPO test pass(no regression)/
test 仍 SKIPPED 但 skip reason 更新指向新 follow-up。

## What we built

- `training/paradigms/ppo/_rollout.py:130`(card_pool)+ `_rollout.py:131`
  (obs_mask sibling)+ `_async.py:59`(card_pool)共 3 处 broken
  `list(getattr(scen, X, ())) or Y` pattern 改为
  `list(getattr(scen, X, None) or ()) [or Y]`。语义:None / 缺失 / 空 list 三者
  统一为空 iter,**`or` 在 `list()` 前 evaluate** 而非后(原 broken 写法 fallback
  永不 trigger)。
- `training/tests/test_ppo_smoke_full.py` skip reason 更新:从 "card_pool
  TypeError" → "RolloutBuffer overflow (pipeline driver 无 buffer.clear
  orchestration)";module docstring 同步反映新 blocker
- `openspec/changes/ppo-rollout-card-pool-none-fix/{proposal,tasks,design}.md`
  完整记录 propose + impl + retrospective

## Tradeoffs revisited

**Tradeoff #1: scope expansion vs strict 1-line fix**
- Active 阶段 proposal 设想:1-line `card_pool` fix → unskip test → PASS
- Verify 后实际:fix 真生效但 smoke_full 仍 fail(distinct bug),scope 边界
  抉择
- **决策:** 保持 1-line scope(per 任务 spec wording),拆 `ppo-buffer-clear-
  orchestration` 为 NEW follow-up。理由:(a)buffer-clear 跨 protocols
  +pipeline +paradigm 是 architecture-level 改造,不 deserve 混进 1-line fix
  change;(b)separate change 历史更清晰,git log 可追溯;(c)CLAUDE.md
  "每个逻辑单元一个 commit / 一个 change" 原则。

**Tradeoff #2: 加 `obs_mask` sibling fix(原 spec 未提)**
- 同根因(`list(getattr(…, ())) or …` pattern 同样在 `scen.obs_mask=None` 时
  raise)
- 不加 → 修了 card_pool 但 obs_mask 仍崩,无意义
- **决策:** bundle。属于 "fix the bug" 而非 "expand scope"。

**Tradeoff #3: 加 SHALL invariant about None handling**
- proposal 中考虑过 `paradigm-ppo/spec.md` "None 输入 fallback 必空 iter"
- **决策:** 不加。判断过度规约(Python 1-line idiom)+ 已被
  `training-architecture` N1.2 cfg dataclass 隐含覆盖 + smoke_full PASS 是
  effective guard(待 `ppo-buffer-clear-orchestration` ship 后生效)

## Surprises

- **Surprise #1**:`getattr` 第三参数 fallback 语义只在 attr **不存在** 时
  trigger,attr 存在但 value 为 `None` 时 default 被 ignored — 这是 Python 文档
  契约的精确含义,但很多人(包括原作者)误以为 default 处理 `None`。3 处 broken
  pattern 全是这个误解的产物。
- **Surprise #2**:`obs_mask` 与 `card_pool` 仅相邻 1 行,同 broken pattern,
  之前 SF-105 task analysis 只列了 `card_pool` — 说明 review 时未细看 sibling
  上下文。
- **Surprise #3**:任务 spec 假定 1-line fix → smoke_full PASS 是 incorrect
  premise — 实际 PPO smoke_full 路径有至少 2 个 distinct bug 串联,fix 一个
  暴露下一个。memory `project_smoke_full_discovered_bugs_2026_05_17` 列了 4
  paradigm bugs 但 PPO 算 1,实际是 ≥2(card_pool/obs_mask 一类 + buffer-clear
  另一类)。
- **Surprise #4**:Buffer protocol 注释(`training/core/protocols.py:209`)
  明示 `clear() called by on-policy paradigms (PPO) per iter`,但驱动从未 wire —
  说明 protocol 注释和实际实现脱节,可能是 P3-A 拆分 driver 时遗漏了 PPO
  on-policy 的 epilogue。

## Spec delta summary

无 SHALL 变化 — 本 change 是纯 implementation bug fix,无 contract 改动。考虑过
加 `paradigm-ppo` SHALL invariant about None handling 但判定过度规约(详
Tradeoffs #3)。

NEW follow-up `ppo-buffer-clear-orchestration`(等下次 propose)将可能涉及:
- `training-architecture` 可能加 SHALL "on-policy paradigm 必须 wire
  buffer.clear() epilogue"
- `paradigm-ppo` 可能加 SHALL "PPO step_schedule 暗示 buffer.clear after train"
- 或 `protocols.py` 加 `StepPlan.clear_buffer_after_train: bool` 字段
- 具体方案待 `/opsx:propose` 时探索
