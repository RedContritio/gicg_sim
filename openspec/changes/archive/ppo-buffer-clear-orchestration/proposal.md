# ppo-buffer-clear-orchestration — Pipeline driver wire on-policy buffer.clear() per PPO iter

**Status:** Active change(propose 阶段,即将 impl + verify + archive in single session)
**Date opened:** 2026-05-17
**Supersedes:** None
**Affected specs:**
- `training-architecture/protocols.md`(StepPlan dataclass 加 1 字段 + on-policy buffer epilogue 不变量)
- `paradigm-ppo/spec.md` § P4.1 反向验证(暂不改;契约 already SHALL,本 change 落地 driver 调用而非 spec 改动)

## Why

姊妹 `ppo-rollout-card-pool-none-fix`(commit `b5c8f4e`)修完 PPO 3 处
`list(getattr(scen, X, ())) or Y` broken pattern 后,PPO smoke_full 仍 SKIP,
verify 暴露 deeper bug:

```
RuntimeError: RolloutBuffer.push: over capacity=500;
clear() between iters
```

根因:

- `Buffer` protocol 注释(`training/core/protocols.py:209`)显式预期
  "`clear()` called by on-policy paradigms (PPO) per iter"
- `paradigm-ppo` spec § P4.1 SHALL "Rollout buffer SHALL be cleared after
  each optimization iteration(on-policy invariant)"
- 但新 pipeline driver(`training/core/pipeline.py`,post P3-A 拆分)从未
  wire 此调用 — collector push 后只 sample + train,**没有 epilogue
  clear()**
- PPO 是 5 paradigm 中**唯一** on-policy(AZ FIFO replay / DMC TDLambdaBuffer
  off-policy / CFR reservoir / BC static dataset),后 4 个都不需要 per-iter
  clear,所以 P3-A 拆分时这个 PPO-specific 收尾被遗漏
- 第 2 outer iter `collector.collect` push 时,buffer 仍持有第 1 iter 的
  `n_games × max_steps × 2 sides ≈ 120` transitions(smoke cfg),capacity
  500 在多 iter 累积下必 overflow

姊妹 change `design.md` "Surprise #4" 已指出 protocol 注释与 driver 实现脱节,
本 change 正是补上这道缝。

## What

**Strategy(Option B,per cascade memory):** `StepPlan.clear_buffer_after_train: bool`
field。paradigm 在 step_schedule 时显式声明 clear intent,driver post-train
检查 + condition clear。**默认 False**,保持其它 4 paradigm 行为不变。

具体改动:

1. `training/core/protocols.py` — `StepPlan` dataclass 末尾加 1 字段:
   ```python
   clear_buffer_after_train: bool = False  # on-policy paradigm 显式声明(PPO)
   ```
   位置:`advance_step: int = 1` 之后(同为带 default 的 trailing 字段,frozen
   dataclass 兼容)。

2. `training/core/pipeline.py` — train loop **之后**、advance 之前加 epilogue:
   ```python
   if plan.clear_buffer_after_train:
       buffer.clear()
   ```
   位置:train block 末尾(`logger.add_scalar(...)` 之后,`if plan.eval` 之前)。
   语义:**only 当 plan.train 真实跑 + plan flag 显式 True 时 clear**;
   collect-only step / sample-不足 short-circuit 时不清(尽管 PPO 不会触发这两
   分支,边界仍 honor)。

3. `training/paradigms/ppo/paradigm.py` — `step_schedule` steady path 中
   `StepPlan(...)` 加 `clear_buffer_after_train=True`:
   ```python
   return StepPlan(
       collect=True,
       n_episodes=pcfg.rollout.n_games_per_iter,
       train=True,
       n_train_batches=pcfg.n_epochs,
       batch_size=pcfg.minibatch_size,
       eval=True,
       advance_step=1,
       clear_buffer_after_train=True,  # PPO on-policy P4.1
   )
   ```
   `total_iterations` reached 的 empty-plan 分支 **不**加(没 train 也没必要 clear)。

4. `training/tests/test_ppo_smoke_full.py` — **计划** unskip,实际 verify 后
   保持 skip 但 reason 指向新 cascade `paradigm-head-kinds-deterministic-iter`
   (详 "Discovery during verify" 段)。

5. **Spec deltas:**
   - `training-architecture/protocols.md` 加 SHALL "on-policy paradigm SHALL
     声明 buffer.clear epilogue via StepPlan.clear_buffer_after_train",
     driver SHALL honor。
   - `paradigm-ppo/spec.md` § P4 P4.1 已是 SHALL(无 spec 改动,但 § P4 段
     可 inline cross-ref pipeline driver 落地路径)— 实际本 change 落地的是
     spec 已规定的契约,故不重复 SHALL,只在 protocols 加 epilogue 通用契约。

## Discovery during verify(scope-relevant)

Implement 完成后 verify 暴露 third-deeper cascade bug,**distinct root cause**:

```
RuntimeError: The size of tensor a (32) must match the size of tensor b
(224) at non-singleton dimension 1
(Adam optimizer.step() resume 路径)
```

诊断(此 change verify 阶段已完成):

- `training/core/network/actor_critic.py:258` `for kind in head_kinds:` 直接
  迭代 `set` parameter,**非确定顺序**(set iteration depends on PYTHONHASHSEED
  hash → 不同 Python 进程不同顺序)
- 5 subprocess 实测:`net.heads.named_parameters()` 顺序在 process 1/2/5 是
  `policy → value`,在 process 3/4 是 `value → policy` —**完全 50/50 分布**
- ckpt save 时 process A 的 net.parameters() order = A',resume 时 process B
  的 order = B' ≠ A',optimizer.state_dict 的 `state` keys(param positional
  id)按 A' 序号存,load 到 B' 时与新 param 错位 → Adam `exp_avg` 与 grad
  shape 错配 → `lerp_` raise

**影响范围:5/5 paradigm 中所有 multi-head paradigm:**
- PPO `{policy, value}` — affected(本 change verified)
- AZ `{policy, value, delta}` — affected(待 verify;smoke_full 当前因 pool
  spec type 已 skip)
- CFR `{avg_policy, value}` — affected(待 verify;smoke_full 当前因 driver
  buffer 已 skip)
- BC — uses BCAgent 自己装配,可能不 affected(待 audit)
- DMC `{q}` — 单 head,**not** affected(已 verified DMC smoke_full PASS)

**判断:** 此 bug 是 distinct root cause,跨 `network-architecture` capability
跨 5 paradigm 共享 backbone,~1-line code fix(`for kind in
sorted(head_kinds):`)+ spec invariant("head_kinds iteration SHALL be
deterministic"),**不属于本 change scope**(本 change 是 PPO on-policy
buffer-clear orchestration,纯 driver epilogue wire,与 network backbone
parameter ordering 是不同 capability)。

本 change 完成 buffer-clear fix(verified 5 iter 无 overflow + 50 iter train
成功 + 3+ ckpts saved)+ 更新 test skip reason 指向新 follow-up
`paradigm-head-kinds-deterministic-iter`(NEW,见 "Out of scope" 段)。

## Out of scope

- **`paradigm-head-kinds-deterministic-iter`** (NEW follow-up,见 Discovery 段)—
  PPO smoke_full 真正 PASS 的剩余 blocker,跨 5 paradigm 共享 backbone(network-
  architecture capability),~1-line code fix + spec invariant,**不属于本 change
  scope**(本 change 是 PPO on-policy buffer epilogue,与 multi-head parameter
  ordering 是不同 capability)
- AZ / DMC / CFR / BC paradigm step_schedule 改动 — 4 paradigm off-policy /
  dataset-driven,**不**需要 per-iter clear,本 change 不动
- Buffer protocol 改动 — `clear()` 方法 already exist on `Buffer` protocol
  (line 215),实现 already 在 `RolloutBuffer.clear` (line 44),本 change
  只 wire driver epilogue
- on-policy 通用框架重构 — 单 paradigm(PPO)足以走 StepPlan flag path;若未来
  加第 2 个 on-policy paradigm 可考虑提取
- PPO 算法 refactor(本 change 纯 orchestration fix)
- 其它 smoke_full follow-up(`az-pool-spec-type-fix` / `cfr-driver-buffer-multihead-fix`
  / `bc-smoke-dataset-fixture`)— 各自独立 change

## Acceptance(actual,revised per Discovery)

1. `pytest training/tests/test_ppo_smoke_full.py -v -m smoke_full` SKIPPED
   (新 reason 指向 `paradigm-head-kinds-deterministic-iter` cascade;原
   "RolloutBuffer overflow" reason 消失)
2. **手 verify**:直接 run driver subprocess `tools.run configs/ppo/smoke_full.toml
   --max-steps 5`,train 5 iter no overflow(原 baseline 在 iter 2 必 raise
   `RolloutBuffer.push: over capacity=500`)— 证 fix 生效
3. **额外手 verify**:50-iter full run,trains + saves ≥ 3 ckpts,直到 resume
   path 才暴露 third-deeper cascade(证 buffer-clear part 真完整)
4. `pytest training/tests/test_ppo_*.py` 全 pass(40 passed),no regression
5. `pytest training/tests/test_{az,bc,cfr,dmc}_*.py` 全 pass(404 passed),
   no regression(StepPlan field default False,4 paradigm 无变化)
6. `tools._meta.check_openspec_indices` pass
7. `tools._meta.check_line_limits` pass
8. memory `project_smoke_full_discovered_bugs_2026_05_17` follow-up queue
   不变(PPO 项 stays in skip,但 blocker 进一步 refined 从 buffer-clear
   层 → head_kinds determinism 层;queue 加 1 项 `paradigm-head-kinds-
   deterministic-iter`)

## Verification

```bash
# Primary: smoke_full SKIPPED with new reason
.venv/bin/python -m pytest training/tests/test_ppo_smoke_full.py -v -m smoke_full --tb=short

# Acceptance #2-3:手 verify driver 不再 overflow
.venv/bin/python -m tools.run configs/ppo/smoke_full.toml --override checkpoint.artifacts_root=/tmp/ppo_verify --max-steps 5
# 期望:`[tools.run] final: step=5 ...`(原 baseline 在 step=1-2 必 raise RolloutBuffer overflow)

# Regression: PPO 其它 test
.venv/bin/python -m pytest training/tests/test_ppo_*.py -v --tb=short

# Regression: 其它 4 paradigm StepPlan field default 0 影响
.venv/bin/python -m pytest training/tests/test_az_*.py training/tests/test_bc_*.py training/tests/test_cfr_*.py training/tests/test_dmc_*.py -v --tb=short

# Lint
.venv/bin/python -m tools._meta.check_openspec_indices
.venv/bin/python -m tools._meta.check_line_limits
```

## Cross-references

- 上游 cascade `ppo-rollout-card-pool-none-fix`(archived 2026-05-17, commit
  `b5c8f4e`)— 本 change 是其 verify-time 发现的 deeper bug 的独立 fix
- `paradigm-smoke-full-tier`(#6, archived 2026-05-17)SF-105 — 4 paradigm
  skip + follow-up queue;本 change 是其中之一
- memory `project_smoke_full_discovered_bugs_2026_05_17` — 4 follow-up queue
- memory `project_session_ship_2026_05_17_core_network_redesign` — D-501 +
  P3-A driver 拆分 context(PPO epilogue 此时遗漏)
- Buffer protocol contract: `training/core/protocols.py:206-218`
- PPO § P4.1 SHALL: `openspec/specs/paradigm-ppo/spec.md:76-78`
- New cascade discovered: `make_actor_critic` head_kinds set 迭代 →
  `training/core/network/actor_critic.py:258` 待修(`paradigm-head-kinds-deterministic-iter`)
