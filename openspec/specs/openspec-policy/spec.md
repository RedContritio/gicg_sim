---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: openspec-policy
---

# OpenSpec Policy — 治理自身的元规约

> OpenSpec 治理自身。本 spec 规定 OpenSpec artifact 的文件多长、放哪、
> 何时拆、如何 archive。所有后续 capability spec / change / archive 操作
> 都参照本 spec。
>
> 这是 OpenSpec **自身的 capability spec**:它的存在使 OpenSpec
> 成为可自审计的对象,而不是仅是工具产物。

## 1. Purpose

OpenSpec 在本 repo 内的使用方式必须自身被规约化,否则会出现:
- spec 文件无限长,失去"可索引、可 grep、可 diff"特性
- `openspec/` 与 `docs/` 边界模糊,规约和实验混淆
- archive 操作随意,history 不可追溯

本 spec 提供 5 大类约束:
- **文件布局**(详 [`./file-layout.md`](./file-layout.md))
- **行数与字节阈值**(详 [`./thresholds.md`](./thresholds.md))
- **内容边界**(详 [`./content-boundary.md`](./content-boundary.md))
- **Archive workflow**(详 [`./archive-workflow.md`](./archive-workflow.md))
- 顶层 invariants(本文件)

## 2. Scope

**In scope**:
- `openspec/` 目录内一切 artifact(capability spec / change / project.md)
- `openspec/` 与 `docs/` 之间的内容归属判定
- `/opsx:*` 命令族行为的 spec 侧约束
- `tools/_meta/` 下未来落地的 enforcement 工具(`check_line_limits.py`
  扩展、`check_openspec_indices.py`、`openspec_archive.py`)的 invariant

**Out of scope**:
- 代码侧文件(Go / Python / Lua)的行数阈值 — 继续由
  `tools/_meta/check_line_limits.py` + `AGENTS.md` 管
- `docs/` 内部 markdown 的具体写法 — 仅约束阈值与归属,内容自由
- OpenSpec CLI 本身的实现(上游工具)— 仅规约 repo 内**使用约定**

## 3. Core SHALL invariants

以下 13 条 invariant 是本 capability 的硬约束。任意冲突应作为
OpenSpec change 提案修订,而非在文件中静默偏离。

1. **内容边界**:`openspec/` SHALL contain "what the system is / must be"
   (规约 / 决策 / 提案);`docs/` SHALL contain "what we learned / tried /
   discovered"(实验 / 复盘 / 历史)。详 [`./content-boundary.md`](./content-boundary.md)。

2. **Capability spec 入口**:`openspec/specs/<capability>/spec.md` SHALL 是
   该 capability 的唯一入口文件,SHALL ≤ 300 行。

3. **Subtopic 阈值**:同一 capability 目录下的 subtopic 文件
   (`openspec/specs/<capability>/<subtopic>.md`)SHALL ≤ 400 行。

4. **Change 阈值**:`openspec/changes/<id>/proposal.md` SHALL ≤ 300 行;
   `design.md` 单文件 SHALL ≤ 500 行(超过时拆为 `design/*.md`
   子文件,每个 ≤ 400 行);`tasks.md` 同规则。详 [`./thresholds.md`](./thresholds.md)。

5. **Spec delta 阈值**:`openspec/changes/<id>/specs/<affected>/spec.md`
   (change 对 capability spec 的修订片段)SHALL ≤ 300 行。

6. **索引强制**:主 `spec.md` SHALL 维护一个 `## Subtopics` 段,列出
   同目录下所有 sibling spec 文件 + 一行说明。新增 subtopic 时 SHALL
   同步更新该索引;`tools/_meta/check_openspec_indices.py` 会自动校验。

7. **Inheritance 字段 registry**:cfg 中可继承字段(初期 `device` +
   `seed`)SHALL 由 `tools/_meta/inheritance.py` registry 实现 fallback
   chain,详见 cfg-schema capability spec(本 task 不展开)。新字段加入
   SHALL 走 OpenSpec change。

8. **Archive workflow**:`/opsx:archive <change-id>` SHALL 执行
   5 步 SOP — verify tasks ✓ / spec delta merge / 行数复检 / design
   摘要化 / git mv。任一步失败 SHALL exit non-zero,不静默。详
   [`./archive-workflow.md`](./archive-workflow.md)。

9. **project.md 过渡条款**:`openspec/project.md` SHALL be the
   project-level spec entry while OpenSpec ≤ 1.x;migration to
   `config.yaml` SHALL go through a standard OpenSpec change once
   OpenSpec ≥ 2.0 lands。OpenSpec 1.3.1 上游已将 project.md 视为
   legacy,本 repo 显式以 change 形式承接迁移,不静默切换。

10. **新 capability 起步**:新建 capability spec SHALL 按
    [`./file-layout.md`](./file-layout.md) 的 Layout 1 模板初始化(至少
    `spec.md` 主入口 + Subtopics 段;subtopic 按需添加)。

11. **行数 enforcement**:阈值违规 SHALL 由 pre-commit hook
    (`tools/_meta/check_line_limits.py` 扩展,P0-T4 后落地)检测并
    REJECT commit,除非显式 `SKIP_LINE_LIMIT_HOOK=1` bypass。Bypass
    commit 的 commit message SHALL 说明原因。

12. **索引 enforcement**:索引一致性 SHALL 由
    `tools/_meta/check_openspec_indices.py`(P0-T5 后落地)校验:
    遗漏 sibling、断链、subtopic 不在索引中 → REJECT。

13. **Inheritance hard defaults**:`device` 的 hard default 为
    `"cpu"`;`seed` SHALL NOT have a hard default — `meta.seed` 必须在
    cfg 显式给出,registry resolver 不替缺失 seed 兜底。详 cfg-schema
    capability spec。

## 4. Subtopics

本 capability 由本文件 + 4 个 subtopic 组成。每个 subtopic 专注一组
正交规则,主 spec.md 只列 SHALL invariant 概要,细节落 subtopic。

- [File layout](./file-layout.md) — 每种 OpenSpec artifact 的标准
  目录布局(capability spec / change / paradigm dossier / active vs
  archived)+ 何时预拆 vs 后拆
- [Line/byte thresholds](./thresholds.md) — spec.md / subtopic /
  proposal / design / tasks 的行数与字节阈值表 + 触发线规则 +
  bypass env vars
- [Content boundary](./content-boundary.md) — `openspec/` 与 `docs/`
  内容归属判定矩阵 + SHALL/IS 句 vs 观察/postmortem 区分线 +
  跨边界 ADR 处理
- [Archive workflow](./archive-workflow.md) — `/opsx:archive` 5 步
  SOP + spec delta merge 协议 + archive 触发条件 + 禁止 archive 场景

## 5. Cross-references

**Project-level**:
- [`openspec/project.md`](../../project.md) — 项目立约(architecture
  / paradigm landscape / tech stack)。本 spec 治理它的存在形式;
  它治理项目内容。

**Sibling capability specs**(后续 P1+ task 落地,本 task 不创建):
- `openspec/specs/cfg-schema/` — Inheritance 字段 registry 详细规约
- `openspec/specs/runs-registry/` — `docs/runs/registry.md` 数据契约
- `openspec/specs/paradigm-*/` — paradigm dossier 落地(AZ / CFR / BC / DMC / PPO)

**Repo conventions**:
- `AGENTS.md`(repo 根)— 开发流程、构建测试和提交检查概览。本 spec 与
  `AGENTS.md` 不重叠：`AGENTS.md` 写如何操作，本 spec 写必须满足什么。
- 客户端注入的跨项目协作规则不属本 spec 治理范围。

**Tool 落地路线**(本 spec 落地但工具实施在后续 task):
- P0-T4:扩展 `tools/check_line_limits.py` → `tools/_meta/check_line_limits.py`
  接入本 spec 表 1 阈值
- P0-T5:新建 `tools/_meta/check_openspec_indices.py` 实施 invariant 6 + 12
- P0-T6:pre-commit hook 串接 P0-T4 + P0-T5
- P0-T7:新建 `tools/_meta/inheritance.py` registry 实施 invariant 7 + 13
- P0-T8:`/opsx:archive` 自动化(`tools/_meta/openspec_archive.py`)实施
  invariant 8 全自动化(在此之前人工按 SOP 跑)

## 6. Status

- **Created**:2026-05-15(P0-T3)
- **Version**:0(初始落地)
- **Expected revision triggers**:
  - OpenSpec 上游 ≥ 2.0 发布、project.md → config.yaml 迁移启动
  - Inheritance registry 新增字段(超出 `device` + `seed`)
  - Archive 自动化 (`openspec_archive.py`) ship,SOP 由人工转自动
  - 阈值表实测后微调(如 subtopic 400 行不够用,改 500)
