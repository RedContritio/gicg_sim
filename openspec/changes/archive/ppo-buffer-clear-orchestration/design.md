# ppo-buffer-clear-orchestration — Design Retrospective

> Archive-time retrospective(≤ 200 行 per archive-workflow.md Step 4)。本 change
> 是中型 follow-up(~66 LOC code/spec + ~330 LOC docs),无 design/ subdir 拆分
> 必要;本文档完整记录 verdict + tradeoff + surprise + spec delta。

## Verdict

**部分成功** — 任务 spec 描述的 PPO on-policy `buffer.clear()` orchestration 真
正落地(StepPlan field + driver epilogue + PPO step_schedule wire),5 iter +
50 iter full run 直接 verified 不再 raise `RolloutBuffer.push: over capacity`,
trains successfully + saves ≥ 3 ckpts。

但 **smoke_full 仍 SKIP** — verify 暴露 third-deeper cascade(distinct root
cause):resume 路径 `Adam optimizer.step` raise tensor shape mismatch。诊断
后发现根因是 `training/core/network/actor_critic.py:258` `for kind in
head_kinds:` 直接迭代 `set`,**非确定 iteration order(set hash 依赖
PYTHONHASHSEED,每 process 不同)**→ ckpt save process A 的 `net.parameters()`
order 与 resume process B 的 order 不同 → optimizer.state_dict 的 `state`
keys(param positional id)与新 model param 错位 → Adam exp_avg / grad shape
错配 raise。

**5/5 paradigm 中所有 multi-head paradigm affected(PPO/AZ/CFR),DMC 单 head
不 affected(已 verified DMC smoke_full PASS)。** 跨 capability network-
architecture / 5 paradigm 共享 backbone,~1-line code fix(`for kind in
sorted(head_kinds):`)+ spec invariant,**不属于本 change scope**(本 change
是 PPO buffer-clear orchestration)。NEW follow-up
`paradigm-head-kinds-deterministic-iter` queued。

实施 ~66 LOC code/spec + 330 LOC docs / 40 PPO test pass + 404 其它 paradigm
test pass(no regression)/ test 仍 SKIPPED 但 skip reason 更新指向新 cascade
+ spec delta 已 merge。

## What we built

- `training/core/protocols.py`:`StepPlan` dataclass 加 `clear_buffer_after_train:
  bool = False` field(位置在 `advance_step: int = 1` 之后,trailing-default
  顺序兼容 frozen dataclass)+ docstring 更新声明 on-policy paradigm 显式
  epilogue 意图
- `training/core/pipeline.py`:train block 之后(`logger.add_scalar(...)` 之后,
  `if plan.eval ...` 之前)加 conditional epilogue:
  ```python
  if plan.clear_buffer_after_train:
      buffer.clear()
  ```
  与 `if plan.train` 独立 if(honor flag 无论 train block 是否真跑)
- `training/paradigms/ppo/paradigm.py`:`step_schedule` steady path
  `StepPlan(...)` 加 `clear_buffer_after_train=True`(8 字段);empty-plan
  分支不加(无 train,无意义)+ docstring 更新
- `training/tests/test_ppo_smoke_full.py`:保留 `@pytest.mark.skip` decorator
  但 reason 从 "RolloutBuffer overflow" → "Adam optimizer.state_dict resume
  desync via non-deterministic head_kinds set iteration";module docstring
  "STATUS" 段加 cascade #2(本 change)+ #3(新 cascade)
- `openspec/specs/training-architecture/protocols.md` § 4 ADD 1 SHALL:
  "On-policy paradigm SHALL set `clear_buffer_after_train=True`,driver SHALL
  honor"(driver vs paradigm 双向契约 + failure mode 注解)
- `openspec/changes/ppo-buffer-clear-orchestration/{proposal,tasks,design,
  specs/training-architecture/spec}.md` 完整记录 propose + impl + retrospective

## Tradeoffs revisited

**Tradeoff #1: StepPlan field vs Buffer protocol attribute**

- 设想:Option B(StepPlan flag,paradigm-driven)优于 Option A(Buffer
  attribute,buffer-driven)— 不扩 Buffer protocol、paradigm 自决、零影响
  其它 4 paradigm
- 实际:**符合预期**。其它 4 paradigm test 404 个全 pass,zero regression。
  PPO test 40 个全 pass。StepPlan field default False 真正零副作用。

**Tradeoff #2: epilogue location(train block 后 vs advance 后)**

- 设想:train block 后(与 train 紧邻,与 advance_step 解耦)
- 实际:**符合预期**。该位置 buffer-clean 早于 eval / ckpt,语义清晰。

**Tradeoff #3: 加 spec SHALL vs 不加(只是 implementation defect 补)**

- 设想:加 `training-architecture/protocols.md` § 4 1 SHALL(on-policy
  paradigm + driver 双向契约),Surprise #4(姊妹 change)指出注释与 driver
  实现脱节是根因,spec SHALL 补上才不会再脱节
- 实际:**符合预期**。SHALL 落地后,任何新 on-policy paradigm 自动有契约
  guard,driver 实现侧 + paradigm step_schedule 侧双向 visible。

**Tradeoff #4: PPO empty-plan 分支也 set vs 只 steady set**

- 设想:只 steady set(total_iterations reached 时已无 train,clear 无意义)
- 实际:**符合预期**。empty-plan 分支 `clear_buffer_after_train` 用 default
  False,driver `if plan.clear_buffer_after_train` 不触发,行为符合"已不 train
  就不 clear"语义。

**Tradeoff #5(unplanned): scope expansion vs strict buffer-clear-only**

- Active 阶段未预设:fix 后 smoke_full 仍 fail 怎么办?是否扩 scope 修第二个 bug?
- Verify 后 cascade root cause clearly 跨 capability(network-architecture vs
  本 change 的 training-architecture)+ 跨 5 paradigm 共享 backbone vs 单 PPO
- **决策:** 保持 buffer-clear-only scope,拆 `paradigm-head-kinds-deterministic-
  iter` 为 NEW follow-up。理由:(a)head_kinds determinism 是 network-
  architecture capability,与本 change 的 training-architecture buffer epilogue
  完全不同;(b)5 paradigm 共享 backbone fix 不应混进单 paradigm scope;
  (c)CLAUDE.md "每个逻辑单元一个 commit / 一个 change" + cascade implementer
  prompt 显式 escalate guidance "若 fix 后暴露 ANOTHER cascade → DONE_WITH_CONCERNS
  queue"

## Surprises

- **Surprise #1**:Python `set` iteration order **真的** hash-seed dependent
  跨 process — 5 subprocess 实测 `{'policy', 'value'}` 在 process 1/2/5 是
  `[policy, value]`,process 3/4 是 `[value, policy]`,完全 50/50 分布。同
  process 内多次 build 顺序 stable(预期),但**跨 process 不稳**(scrutiny 后
  才意识到)— 这是 PyTorch save/load 跨 process 静默 bug 的经典模板。
- **Surprise #2**:本 cascade 比预期更深 — `ppo-rollout-card-pool-none-fix`
  Surprise #4 已指出 protocol 注释 vs driver 实现脱节,本 change 修完后仍
  暴露 third-deeper bug(network-architecture 层 head_kinds set iter)。 memory
  `project_smoke_full_discovered_bugs_2026_05_17` 列 4 paradigm bugs 但 PPO 算
  1,实际 ≥ 3(card_pool/obs_mask + buffer-clear + head_kinds determinism)。
- **Surprise #3**:第一次手动 probe 看 ckpt opt state shapes 时,(64, 224) +
  (64, 32) 都 match 看似 OK — 直到看到 `param[117]` 与 `param[121]` 在 fresh
  model 与 ckpt 对照 shape 错位(64, 224) ↔ (64, 32) 才意识到不是 shape bug
  是 ordering bug。**诊断需要双向对照 ckpt opt state ↔ fresh model param
  positional indices**,不能只看单边。
- **Surprise #4**:DMC smoke_full PASS 表面上没 illumiate 此 bug — 因为 DMC
  uses 单 head `{'q'}`,1-element set 顺序 trivially deterministic。本 change
  之前 4 paradigm `project_smoke_full_discovered_bugs_2026_05_17` queue 都标
  paradigm-local bug,但 head_kinds determinism 是**跨 5 paradigm 共享 backbone
  bug**,只在 multi-head + resume path 才暴露。

## Spec delta summary

**ADD** to `openspec/specs/training-architecture/protocols.md` § 4 Buffer
protocol 末尾:

- SHALL #4:On-policy paradigm SHALL set `StepPlan.clear_buffer_after_train=True`
  声明 per-iter clear intent;Driver SHALL honor 此 flag(train block 后,
  eval / ckpt 前 调 `buffer.clear()`);Off-policy / dataset-driven paradigm
  SHALL 保留 default False。加 Rationale(paradigm-agnostic storage 抽象 +
  paradigm 决策权)+ Failure mode 注解(PPO 第 2 iter 必 raise overflow)+
  wire commit 锚点。

`last_updated` 从 2026-05-15 → 2026-05-17。

无其它 spec 改动 — `paradigm-ppo/spec.md` § P4.1 already SHALL("Rollout
buffer SHALL be cleared after each optimization iteration"),本 change 落地
driver 调用而非 spec 改动。

NEW follow-up `paradigm-head-kinds-deterministic-iter`(下次 propose)将可能涉及:
- `network-architecture/spec.md` 加 SHALL "head_kinds iteration SHALL be
  deterministic across process(SHALL sort before construct ModuleDict)"
- `make_actor_critic` 改 `for kind in sorted(head_kinds):`(1-line code fix)
- 5 paradigm 共享 backbone 影响 audit + multi-head paradigm resume test
- 具体方案待 `/opsx:propose` 时探索
