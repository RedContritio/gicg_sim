---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: bc-pipeline-collect-gate-fix
---

# Proposal — bc-pipeline-collect-gate-fix

## 1. Why

`bc-smoke-dataset-fixture`(archived 2026-05-17 commit `88833d9`)闭了
BC smoke_full 的 fixture skip,但同时 **discovered + 显式 defer** 一个
更深的 pipeline bug:

`training/core/pipeline.py:83` collect gate:

```python
if plan.collect and plan.n_episodes > 0:
    ...
    out = collector.collect(plan.n_episodes, provider)
    buffer.push(out)
```

BC paradigm `step_schedule`(`training/paradigms/bc/paradigm.py:122-158`)
返回 `collect=True, n_episodes=0`(BC 是 dataset-driven,没有 episodes
概念;DatasetCollector.collect 自身 ignore `n_units` 一次性 push 全
static dataset per `collector.py:67-68` docstring)。

结果:`n_episodes > 0` 短路 → collector 永不调用 → buffer 空 →
`pipeline.py:91` `if len(buffer) < plan.batch_size: break` → 100 epoch
全部 train batch skip → `state.train_steps = 0, state.total_transitions
= 0` → ckpt 存的是 **随机初始化权重**,网络从未被训。

A1.6.2 file-existence contract 满足(4 ckpt + latest.pt + metrics.jsonl),
但 A1.6 的 spirit("smoke_full 真训")没满足。`test_bc_smoke_full.py`
docstring KNOWN CONCERN 段记录此 bug,明确 follow-up = 本 change。

非 BC paradigm(AZ / DMC / PPO / CFR)的 `step_schedule` 在 `collect=True`
时 always `n_episodes > 0`(它们都跑 EpisodeRunner,episode 为单位),
terminus 时 `collect=False` → 现有 gate 与新 gate 行为完全等价 → 0 regression。

## 2. What

**单行 fix + 1 个 test assertion**(production 路径 + smoke_full
regression lock):

1. **`training/core/pipeline.py:83`** relax gate:
   ```python
   # before
   if plan.collect and plan.n_episodes > 0:
   # after
   if plan.collect:
   ```
   collector 自身 decide collect 量(BC: 全 dataset;非 BC: `n_episodes`
   episodes via EpisodeRunner)。`plan.n_episodes > 0` 不再是 driver-side
   gate,而是 collector-internal contract。

2. **`training/tests/test_bc_smoke_full.py`** 加 metrics assertion(在
   `verify_ckpt_files` 后):
   - Read `<artifacts>/metrics.jsonl` 所有 iter 行
   - assert 最后一个 iter 的 `train_steps > 0`(MetricsLogger.log_iter
     每 outer iter 输出 step + frames + train_steps,见 `core/logging.py:44-55`)
   - 锁住后续 regression:若 collect gate 再次破 BC train path,此
     assertion fail。

## 3. Affected specs

- `training-architecture/spec.md`:ADD invariant about pipeline collect
  gate semantics — `plan.collect` 是 driver-side 唯一 gate,`plan.n_episodes`
  是 collector-internal contract(non-episode paradigm 可 `n_episodes=0`
  + 仍走 collector path)。

## 4. Out of scope

- **不重写** BC `step_schedule` 让它 emit `n_episodes=dataset_size`
  之类的"假"语义 — BC 没 episode 概念,塞虚数破坏 paradigm-aware
  metadata。
- **不修复** BC paradigm 的其它潜在 issue(loss convergence 验证、
  network architecture 检查等)— 严格 scope:本 change 只闭
  `pipeline.py:83` collect gate + 加 regression lock assertion。
- **不动** 其它 paradigm `step_schedule` 实现 — 它们都 `n_episodes>0`
  when collect,gate relax 后行为 bit-identical。

## 5. Decision summary(详 design.md retrospective)

- **Single-line gate relax vs paradigm-side n_episodes plug**:选 gate
  relax —— BC `n_episodes=0` 是 truthful metadata(no episodes),fix
  应该在 gate side 而不是逼 paradigm 编虚数。Driver gate 设计意图是
  "skip when paradigm idle"(`plan.collect=False`),`n_episodes>0` 是
  redundant 二层 gate,有害无益。
- **Assertion granularity**:metrics.jsonl 最后一行 iter 的 `train_steps>0`
  覆盖大部分 bug,且 robust(不依赖具体 epoch 数 / batch shape)。Backup
  考虑过 ckpt weight delta diff,过于侵入 + 慢,且 metrics assertion 足够。
- **Spec delta in training-architecture**:本 change 加一条 invariant
  显式锁定 `plan.collect` 为 driver-side 唯一 gate,防止后续 refactor
  误恢复 `n_episodes > 0` 旧逻辑。
