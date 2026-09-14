---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
parent: ../tasks.md
---

# Phase 6 — OpenSpec archive workflow

> P3-P5 全 ship + smoke pass → 跑 `/opsx:archive unified-training-pipeline`
> + spec delta merge 进 `openspec/specs/`。一次性 0.5 day。

## 1. 总 LOC 估 / Wall

- **LOC 估**:minor(主要是 git mv + spec delta merge,实际新增 ~200 LOC)
- **Wall 估**:0.5 day
- **门槛**:archive workflow 7 step 全 pass

## 2. P6-T1 Tasks 全 checkbox check

- [x] **P6-T1.1**:`tasks.md` 顶层 + `tasks/phase{3,4,5}-*.md` 全 task
  checkbox = `[x]`(本 phase 列表也要全 checked)
- [x] **P6-T1.2**:无 abandoned task(若有 → 在 design.md 加 retrospective
  说明 + 显式标 `(abandoned)`)
- [x] **P6-T1.3**:P5.5 / P5.6 conditional task(Go 化)标 "deferred to
  follow-up change"

依赖:P5 ship

## 3. P6-T2 Design 摘要化

OpenSpec archive workflow Step 2:design.md 摘要到 ≤ 200 行 retrospective:
- [x] **P6-T2.1**:`design.md` 顶层留 architecture overview + 关键决策
  anchor + Phase 实施摘要表(去除 implementation detail)
- [x] **P6-T2.2**:`design/<10 subtopic>.md` 保留(作为历史 implementation
  record,不删)
- [x] **P6-T2.3**:`design.md` 末尾加 "## Retrospective" section:
  - 实际 LOC vs 估计
  - 实际 Wall vs 估计
  - 偏离 plan 的部分 + 理由
  - 后续 follow-up change list(P5.5 / P5.6 Go 化等)

依赖:P6-T1

## 4. P6-T3 Spec delta merge 进 `openspec/specs/`

OpenSpec archive workflow Step 3:本 change `specs/<cap>/spec.md` delta
内容 merge 到 `openspec/specs/<cap>/spec.md`:

- [x] **P6-T3.1**:`specs/training-architecture/spec.md` 内容 merge 进
  `openspec/specs/training-architecture/spec.md`(modify 形式,P0-T9 ship
  骨架基础 + 本 change 详细)
- [x] **P6-T3.2**:`specs/paradigm-az/spec.md` 移到 `openspec/specs/paradigm-az/spec.md`
  (新 capability,直接 mv)
- [x] **P6-T3.3**:同 P6-T3.2 for paradigm-dmc / paradigm-cfr / paradigm-ppo
  / paradigm-bc
- [x] **P6-T3.4**:`specs/config-schema/spec.md` 移到 `openspec/specs/config-schema/spec.md`
  (新 capability)
- [x] **P6-T3.5**:`specs/tools-layout/spec.md` 同 P6-T3.4
- [x] **P6-T3.6**:`openspec/project.md` 更新 capability 清单(+ 6 新
  capability)
- [x] **P6-T3.7**:check_openspec_indices full tree pass

依赖:P6-T2

## 5. P6-T4 行数复检

OpenSpec archive workflow Step 4:每文件 ≤ thresholds:

- [x] **P6-T4.1**:`tools/_meta/check_line_limits.py` archive 后扫一次
- [x] **P6-T4.2**:若有违反 → 拆 subtopic(后拆原则)
- [x] **P6-T4.3**:`openspec/specs/training-architecture/spec.md` ≤ 300 行
  (本 change 详细 merge 后可能超,届时拆 subtopic)
- [x] **P6-T4.4**:每 paradigm spec ≤ 300 行(初版 ~150-250 行,有空间)

依赖:P6-T3

## 6. P6-T5 git mv archive change 目录

OpenSpec archive workflow Step 5:

- [x] **P6-T5.1**:`git mv openspec/changes/unified-training-pipeline
  openspec/changes/archive/unified-training-pipeline`
- [x] **P6-T5.2**:archive 后路径变 `openspec/changes/archive/unified-training-pipeline/`
- [x] **P6-T5.3**:全 cross-references(other files 引用本 change)更新路径
  - `openspec/specs/training-architecture/spec.md` 引用更新
  - 后续 follow-up change(P5.5 G2 / P5.6 G3)起步 proposal 引用更新

依赖:P6-T4 pass

## 7. P6-T6 文档更新

- [x] **P6-T6.1**:`docs/0_status/README.md` archive 标记 + 当前 phase 切
  到 P5.5(若 trigger 满足)或 idle
- [x] **P6-T6.2**:`docs/0_status/timeline-2026-05.md` 加 2026-05-XX P2-P6
  ship 记录
- [x] **P6-T6.3**:memory `project_training_layout` 加 entry "2026-05-XX
  统一管线 P3-P6 ship,5 paradigm via core + paradigms 二分"

依赖:P6-T5

## 8. P6-T7 最终 commit

- [x] **P6-T7.1**:`git status` clean(除 archive mv)
- [x] **P6-T7.2**:Commit message follow 格式(scope: archive
  unified-training-pipeline + 实际 ship 摘要 + retrospective 链)

依赖:P6-T6

## 9. P6 ship 门槛

P6-T1-T7 全 done → archive 完成。
本 change lifecycle 结束。后续 P5.5 / P5.6 Go 化由独立 change 启动。

## 10. Cross-references

- Archive workflow 主 spec → [`../../../../specs/openspec-policy/archive-workflow.md`](../../../../specs/openspec-policy/archive-workflow.md)
- 主 design retrospective trigger → [`../design.md`](../design.md) Status section
- 主 proposal archive trigger → [`../proposal.md`](../proposal.md) Status section
- P5.5 G2 follow-up change(待启动)→ TBD
- P5.6 G3 follow-up change(待启动)→ TBD
