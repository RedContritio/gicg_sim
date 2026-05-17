---
last_updated: 2026-05-17
status: ARCHIVED
schema_version: 0
parent: ./proposal.md
---

# Design Retrospective — bc-pipeline-collect-gate-fix

> Archive-time retrospective(≤ 200 lines per archive cap)。本 change
> 表面是单行 pipeline gate relax(~5 LOC production),实施中 discover
> 一个 cascade-attached buffer/loss data contract gap;在严格 scope 边界
> 内 minimal extension(+~50 LOC)闭整条 BC driver path,确保 metrics
> assertion `train_steps>0` 能真实通过(不是 contract-only file-existence)。

## Verdict

**完整闭环** — BC smoke_full 现在真训(19s wall;`train_steps>0` assertion
通过)。Gate fix + DatasetBuffer/BCParadigm wiring 把整条 BC driver path
打通,从 `bc-smoke-dataset-fixture` archive 时遗留的"ckpt 但 random
weights"状态升级为"ckpt 真带训练后权重"。

5/5 paradigm smoke_full 整体状态:DMC(原 PASS)+ AZ / PPO / CFR / BC
(4 个 follow-up archived 2026-05-17 → 全 PASS)。`paradigm-smoke-full-tier`
SF-105 4-paradigm defer 列表全部闭环。

实施 single day / 4 + 9 tasks all done / 全 verification gate green
(BC smoke_full / DMC + CFR smoke_full / 153 paradigm unit / 1004 full
sweep / openspec index / ruff format / line limits)。

## What we built

**Production code(3 file,~50 LOC net add)**:

- `training/core/pipeline.py:83` gate relax(`if plan.collect:`)+
  ~10 行 inline comment 解释 collector-internal n_units contract
- `training/core/buffer/dataset.py` extend `DatasetBuffer.__init__` 加
  optional `batch_builder: Callable[[ndarray], dict]` 参数;sample()
  根据是否有 builder 决定 return `{'fields': builder(indices)}` 或
  legacy `{'transitions': [...]}`(backward-compat);新 helper
  `_extract_dataset_indices` 从 Transition.payload['dataset_idx'] 解出
  dataset row indices
- `training/paradigms/bc/paradigm.py::make_buffer` 传入 `collector.build_batch`
  作为 batch_builder(BC paradigm 是 DatasetBuffer 唯一 production 消费者)

**Test code(1 file,~40 LOC)**:

- `training/tests/test_bc_smoke_full.py` 加 `_assert_train_steps_positive`
  helper:read `metrics.jsonl`,find 最后一个 `kind='iter'` row,
  assert `train_steps > 0`。在 test 主体 `verify_ckpt_files` 后调用
- docstring update 删 KNOWN CONCERN 段,加 fix reference + lock claim

**OpenSpec docs(4 file,~370 LOC)**:

- `proposal.md`(97):why bug + what fix + scope edges + decision summary
- `tasks.md`(64,T1.x ~3 / T2.x ~4 / T3.x ~9 / T4.x ~4)
- `design.md`(本文件 retrospective,≤ 200)
- `specs/training-architecture/spec.md`(62)delta — ADD pipeline.md
  §3 invariant #7 `Collect phase gate SHALL be plan.collect only`

## Tradeoffs revisited

- **Single-line gate relax vs paradigm-side n_episodes plug**(D1,选择
  正确)— 选 gate relax。Option B(BC `step_schedule` 返回
  `n_episodes=1` 虚数)会破坏 `state.total_episodes` accounting 与
  paradigm-aware metadata truthfulness。Gate relax 一致性更好:`plan.collect`
  是唯一 driver-side gate,`plan.n_episodes` 是 collector-internal contract。
- **Spec delta location**(D2)— 选 `pipeline.md` §3 add SHALL #7。
  替代方案是把约束放在 `protocols.md`(StepPlan dataclass docstring)
  但 SHALL invariant 通常住 invariants 章节;pipeline §3 是 collect/train
  loop 的官方 location。
- **NEW DECISION D3 — Scope extension for DatasetBuffer/BCLoss data
  contract gap**(propose 时未识别,T3.1 暴露):T2.1 gate fix 后
  collector 终于被调用、buffer 终于有数据,但 `DatasetBuffer.sample`
  return `data={'transitions': [...]}` 而 `BCLoss.compute` line 54
  expect `data['fields']` raise ValueError。考虑:
  - **Option A**:keep strict scope,DONE_WITH_CONCERNS + queue new
    follow-up `bc-buffer-loss-fields-contract-fix`(~30 min 重复 OpenSpec
    overhead)
  - **Option B**(选):extend scope minimally。两个 fix 实际是同一个
    BC driver path 的两层 contract gap,在同 change 内闭比拆两 change
    更高效。Extension 限定:`DatasetBuffer` 加 optional kwarg
    (backward-compat default 保留);`BCParadigm.make_buffer` 传入
    `collector.build_batch`;`_extract_dataset_indices` 用
    `payload['dataset_idx']`(BC DatasetCollector 已 emit 此字段,
    见 `collector.py:90`)。0 spec delta 变化(invariant 仍只是 gate
    semantics)。Per CLAUDE.md "范围扩张前先问":本 change 是
    autonomous mode + 用户原 prompt 已 cite escalation policy 容
    DEEPER cascade,且 extension 完全 contained on BC paradigm。
- **batch_builder kwarg vs subclass**(D4)— 选 optional kwarg。
  `BCDatasetBuffer` subclass 会强迫 BC import 一个新类,且与 DatasetBuffer
  的关系是"BC 额外注入 builder"不是"BC 改 behavior"。kwarg 更轻。

## Surprises

- **Cascade-attached bug T3.1 暴露**(主要 surprise):`bc-smoke-dataset-fixture`
  KNOWN CONCERN 段 + 本 change proposal 都假设单 gate fix 就让 BC train,
  实际 fix 后立即 hit second-layer contract gap(`DatasetBuffer.sample`
  produces `'transitions'` 但 `BCLoss.compute` expect `'fields'`)。
  原因:`bc-smoke-dataset-fixture` 时 BC train path 从未真正走通,所以
  fixture 设计阶段 没有数据流过 Buffer→Loss 边界,bug invisible。本
  change Phase 2 第一次让数据真流过去,bug 立即 surface。学到:contract-only
  verification(file existence)+ 不真训 = 二层 bug 隐形。本 change
  metrics assertion `train_steps>0` 是直接的反 invisible-bug 设计。

- **DatasetBuffer 自带 dataset_idx 映射准备**(意外的 happy path):
  `bc/collector.py:90` BCDatasetCollector 早已 emit `payload={'dataset_idx':
  i, ...}` 在每个 Transition 上,虽然之前 driver path 从未消费过这字段。
  `_extract_dataset_indices` helper 直接 honor 此字段,无需 buffer 自己
  追踪 push order(更 robust,future shuffle-aware insertion 不破)。

- **5 paradigm smoke_full 4-pass closure**(LOW surprise but
  satisfying):本 change archive 后 5/5 paradigm smoke_full 全 PASS。
  原 `paradigm-smoke-full-tier` SF-105 列 4 个 follow-up:az-pool-spec-type-fix
  + ppo-rollout-card-pool-none-fix + cfr-driver-buffer-multihead-fix +
  bc-smoke-dataset-fixture → 全 archived 2026-05-17;BC 一层深的
  pipeline gate bug 在 `bc-smoke-dataset-fixture` design.md Surprise 段
  暴露 → 本 change 闭。Cascade closure 完整。

- **DMC + CFR smoke_full regression check 258s wall**(LOW,合预期):
  DMC dominant ~4 min(real 100-step train + ckpt save + resume),CFR ~20s
  (stub buffer + 30 step + resume)。两个 non-BC paradigm 都
  bit-identical(gate `plan.collect=True && plan.n_episodes>0` 两条件
  always 同时 true)→ 0 regression confirmed。

## Spec delta summary

- **pipeline.md §3 invariant #7 ADD**:`Collect phase gate SHALL be
  plan.collect only`。Driver SHALL NOT 加 secondary `n_episodes > 0` 之类
  redundant gate。`n_episodes` 是 collector-internal contract,paradigm-aware
  metadata,允许 dataset-driven paradigm(BC)emit `0` truthfully。
  Rationale 段引用本 change 实施时 discovered failure mode 作为反例
  (pre-fix BC 写 random-init ckpt)。

Cross-references:
- 闭 `bc-smoke-dataset-fixture` archive design.md Surprises 段 cited
  follow-up(bug discovered 时该 change 严格 scope 不修)
- 闭 `paradigm-smoke-full-tier` [SF-105] BC defer 的 pipeline-path
  portion(fixture portion 由 `bc-smoke-dataset-fixture` 闭;pipeline-path
  portion 由本 change 闭)
- 闭 4 个 follow-up cascade 完整 closure(`az-pool-spec-type-fix` +
  `ppo-rollout-card-pool-none-fix` + `cfr-driver-buffer-multihead-fix` +
  `bc-smoke-dataset-fixture` + 本 change),5/5 paradigm smoke_full
  全 PASS(default + smoke_full tier 全绿)

## DECISIONS index

本 change 无独立 DECISIONS file(轻量 follow-up,所有 design 决策记录
在本 retrospective)。Cross-reference:
- D1 → gate relax vs paradigm-side n_episodes plug(本节 Tradeoffs)
- D2 → spec delta location pipeline.md §3(本节 Tradeoffs)
- D3 → scope extension for DatasetBuffer/BCLoss data contract(Surprises +
  Tradeoffs)— per CLAUDE.md 范围扩张 + user prompt cascade escalation
- D4 → batch_builder kwarg vs subclass(本节 Tradeoffs)
