---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
change_id: unified-training-pipeline
---

# Tasks — unified-training-pipeline 实施 phase 总览

> 顶层 phase 索引 + 进度。详细 task list 见 `./tasks/phase{3,4,5,6}-*.md`。
> P2 本 commit ship proposal + design + tasks + spec delta(本目录),P3-P6
> 由后续 commit 落地。

## 1. Phase 总览

| Phase | 状态 | 内容 | LOC 估 | Wall 估 |
|---|---|---|---|---|
| P0 | ✅ done | OpenSpec 基建 + spec 骨架(8 commits)| ~3000 | done |
| P1 | ✅ done | 历史迁移 + paradigm dossier(9 commits)| ~17000 | done |
| **P2** | **▶ in progress** | **本 change(proposal + design + tasks + spec delta)** | **~5000** | **1 commit** |
| P3 | ☐ next | core scaffold + DMC async 迁移(first migration)| ~3000 new | ~2w |
| P3.5 | ☐ parallel | G1 F1-Dn Go 化 | ~700 | 3-5d |
| P4 | ☐ | AZ + BC + PPO + CFR 适配 EpisodePolicy 接入 | ~3000 | ~2w |
| P5 | ☐ | git mv 物理 paradigms/ + tools 分类 + configs 重组 | ~10000 mv | ~1w |
| P5.5 | ☐ conditional | G2 cgo step+encode 合并(ADR-0019 obs stable 后)| ~900 | 1-2w |
| P5.6 | ☐ conditional | G3 DMC actor Go(DMC F1-D2 ≥0.30 后)| ~2000 | 2-3w |
| P6 | ☐ | OpenSpec archive workflow run | minor | 0.5d |

总实施 LOC 估:~19600(P3-P6,不含 P5 git mv 计数)

## 2. P2 自检(本 change ship 前)

- [x] proposal.md(≤ 300 行)— Why + What + Affected specs + Out of scope
- [x] design.md 顶层(≤ 500 行)— architecture overview + 10 subtopic 索引
- [x] design/10 subdir markdown(每 ≤ 400 行)
- [x] tasks.md 顶层 — phase 索引(本文件)
- [x] tasks/4 phase markdown(每 ≤ 400 行)
- [x] specs/8 spec delta(每 ≤ 300 行)
- [x] `check_openspec_indices` 全 pass(R1+R2+R3)
- [x] `check_line_limits` 本 change 文件全 pass
- [x] Commit message follow ~/.claude/CLAUDE.md §4 格式

## 3. Phase 详细任务

每 phase 在对应 `./tasks/phase<N>-*.md` 列具体 task,标:
- Task ID(`P<N>-T<X>`)
- 内容描述
- LOC 估
- 依赖(blocked by 哪些 task)
- 完成条件(测试 / smoke / metrics 通过门槛)
- Checkbox(`- [ ]` / `- [x]`)

## Subtopics

- [Phase 3 — core scaffold + DMC](./tasks/phase3-core-dmc.md) — core/ 目录
  全建 + DMC 迁移 first paradigm
- [Phase 4 — other paradigms](./tasks/phase4-other-paradigms.md) — AZ +
  BC + PPO + CFR 接入
- [Phase 5 — physical mv + tools](./tasks/phase5-physical-mv-tools.md) —
  git mv + tools/ 重组 + configs/ 重组
- [Phase 6 — archive](./tasks/phase6-archive.md) — `/opsx:archive
  unified-training-pipeline` + spec delta merge

## 4. Cross-references

- 主 design → [`./design.md`](./design.md)
- 主 proposal → [`./proposal.md`](./proposal.md)
- 主 capability spec(P0-T9 骨架,本 change 修订)→
  [`../../specs/training-architecture/spec.md`](../../specs/training-architecture/spec.md)
- OpenSpec archive workflow → [`../../specs/openspec-policy/archive-workflow.md`](../../specs/openspec-policy/archive-workflow.md)

## 5. Status

- **Created**:2026-05-16(P2 commit)
- **P3 start trigger**:本 change ship + controller 批准
- **Archive trigger**:P3-P6 全 ship + smoke pass + spec delta merge
