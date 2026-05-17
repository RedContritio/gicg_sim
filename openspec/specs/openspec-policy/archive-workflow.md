---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
parent: ./spec.md
---

# Archive Workflow — /opsx:archive 5 步 SOP

> 治理 [`./spec.md`](./spec.md) invariant #8。
> 规定 `/opsx:archive <change-id>` 的 5 步 SOP、spec delta merge 协议、
> 触发条件、禁止场景。

## 1. 5 步 SOP

`/opsx:archive <change-id>` SHALL run all 5 steps in order。任一步失
败 SHALL exit non-zero,不静默跳过。

| 步骤 | 行动 | 检查点 / 失败处理 |
|------|------|-------------------|
| 1. Verify tasks ✓ | 扫 `changes/<id>/tasks.md`(或 `tasks/*.md` 全部子文件)checkbox | 任一 `- [ ]` 未勾选 → REJECT,列出未完成 task |
| 2. Spec delta merge | `changes/<id>/specs/<X>/spec.md` 合入 `openspec/specs/<X>/spec.md` | merge 冲突 / 重复 SHALL / 行号错位 → 人工介入,REJECT 自动归档 |
| 3. 行数复检 | merge 后跑 `tools/_meta/check_line_limits.py` | 主 spec.md > 300 行 → 强制拆 subtopic 后才能 archive;Hard fail → REJECT |
| 4. Design 摘要化 | `design.md` 删已完成的细节,留 ≤ 200 行 retrospective | 必含 "verdict + tradeoff revisited"段;无该段 → REJECT |
| 5. git mv | `changes/<id>/` → `changes/archive/<id>/` | git mv 保留历史;mv 后 git status 应 clean(除新 archive commit) |

## 2. 各步骤细则

### 2.1 Step 1 — Verify tasks ✓

扫描:
- `changes/<id>/tasks.md`(顶层,若单文件)
- `changes/<id>/tasks/*.md`(若拆为多 phase 文件)

匹配 `- [ ]` 与 `- [x]` 模式。SHALL 检查:
- 所有 task 是 `- [x]`(完成)
- 没有 `- [~]` / `- [?]` / `- [-]` 等中间态符号
- Phase 索引(若有)的"总进度"段更新到 100%

失败示例:
```
ERROR: 3 tasks incomplete in changes/0023-foo/tasks.md:
  - line 42:  - [ ] T5: implement bar
  - line 51:  - [ ] T6: add tests
  - line 60:  - [ ] T7: update docs
Archive REJECTED.
```

### 2.2 Step 2 — Spec delta merge

对每个 `changes/<id>/specs/<X>/spec.md`(spec delta 文件):

1. 解析 delta 中 `[ADD]` / `[MODIFY]` / `[REMOVE]` 标签
2. **`[ADD]`**:directly append SHALL lines 到对应 capability spec 的对应段
3. **`[MODIFY]`**:diff-based 替换,**SHALL 人工 review**(自动 archive
   工具应 prompt 确认,非确认状态下 REJECT)
4. **`[REMOVE]`**:从对应 capability spec 删除,在 archive 后的
   `design.md` retrospective 段说明删除理由

合并冲突场景:
- 同一 SHALL 行被多个并行 change 同时修改 → REJECT,要求 rebase
- 删除的 SHALL 与其他 capability 仍引用 → REJECT,要求先改引用方
- Capability spec 中找不到 delta 指向的目标段 → REJECT,要求人工
  指定锚点

### 2.3 Step 3 — 行数复检

Merge 后:
1. 对每个被 merge 的 `openspec/specs/<X>/spec.md` 跑
   `tools/_meta/check_line_limits.py`(P0-T4 后落地)
2. 若主 spec.md 行数 > 300(必拆阈值)→ REJECT,要求先拆 subtopic
3. 若已存在的 subtopic 因合入新内容 > 400 → 同理
4. Hard fail 阈值(主 350 / subtopic 500)永远 REJECT,无 SKIP_HOOK 出口

拆分由人工执行(或后续 `openspec_archive.py` 半自动协助),拆好后重跑
archive。

### 2.4 Step 4 — Design 摘要化

`design.md` 在 active 阶段可以长(≤ 500 行,详
[`./thresholds.md`](./thresholds.md));archive 时 SHALL 摘要化到 ≤ 200 行,
内容结构:

```markdown
# <change-id> Design Retrospective

## Verdict
<一句话总评:成功 / 部分成功 / 失败 / 替代方案胜出>

## What we built
<≤ 5 bullet,实际 ship 的东西>

## Tradeoffs revisited
<列出 active design.md 中的 tradeoff,标 "预期 X,实际 Y">

## Surprises
<未在 design.md 中预测但 implementation 中发现的事>

## Spec delta summary
<本 change 对哪些 capability spec 做了什么 SHALL 变化的摘要>
```

原 design.md(active 阶段写的)可保留在 `design-original.md`(可选,
为了历史完整性),也可完全替换 — 由 archive 操作者决定。git 历史保
留全部演化。

### 2.5 Step 5 — git mv

```
git mv openspec/changes/<id>/  openspec/changes/archive/<id>/
```

mv 之后:
- git status 应只显示 archive commit 待 stage 的内容
- 整目录路径变更,文件内容不变(除 design.md 摘要化产生的修改)
- 跨 commit 间 `git log --follow` 可追溯历史

## 3. Archive 触发条件

SHALL 满足全部条件才允许 `/opsx:archive`:

- [x] 所有 tasks 完成(Step 1)
- [x] 实施侧已 commit + tested(代码 / spec 变更已落地;由
      proposal.md 关联的 acceptance criteria 验证)
- [x] Proposal 中预测的 outcomes 已在 design.md retrospective 中
      检验(填"预期 X,实际 Y")
- [x] 行数 / 索引 / lint 全 pass(Step 3 + 上游 pre-commit)

## 4. 禁止 archive 的情况

以下任一情况 SHALL REJECT archive:

- 有未完成 task(`- [ ]`)
- Spec delta 未 merge(Step 2 未执行 / 中途失败)
- 行数超阈值未拆(Step 3 REJECT)
- Design.md 未摘要化(仍 > 200 行或缺 retrospective 段)
- 关联代码 / spec 实施未 ship(commit history 无对应 commit)
- 关联 acceptance criteria 未验证(proposal 列的 outcomes 无对应
  test / metric)

## 5. Spec delta merge 协议

### 5.1 Add(新加 SHALL)

直接 append 到对应 capability spec 的对应段(若 delta 标了 anchor)
或末尾(无 anchor 时)。无需 review,因为是纯增量。

### 5.2 Modify(改 SHALL)

diff-based merge,**SHALL 人工 review**:
- 自动工具显示前后对比
- 操作者确认(`y/N` prompt 或显式 `--confirm-modify` flag)
- 不确认 → REJECT,archive 中断

### 5.3 Remove(删 SHALL)

删除前 SHALL:
- 验证全 repo grep 无对该 SHALL 的引用(其他 spec / docs / 代码注释)
- 在 design retrospective 段写删除理由
- 在 git commit message 显式列出删除的 SHALL 内容

## 6. SHALL

1. `/opsx:archive` SHALL 按 Step 1 → 5 顺序执行;乱序 / 跳步 → REJECT

2. 任一 step 失败 SHALL exit non-zero,stderr 输出失败原因 + 修复
   建议;**不**静默跳过 / 不**记录到 log** 然后继续

3. Archive 操作 SHALL 创建独立 archive commit(不与实施 commit 混
   合),commit message 格式:
   ```
   openspec archive: <change-id>(P<phase>-<task>)

   Verdict: <success | partial | failure | superseded>

   Spec delta merged into:
     - openspec/specs/<X>/spec.md  (<+N / -M SHALL>)
     - openspec/specs/<Y>/spec.md  (<+N / -M SHALL>)

   <一段 retrospective summary,≤ 5 行>
   ```

4. Archive 操作 SHALL NOT 修改 proposal.md(它是"当时的提案"快照,
   保留原貌作历史)

5. Archive 操作 SHALL NOT 创建新 spec.md(spec 创建走 capability
   spec 落地,不是 archive 副作用)

## 7. 自动化路线

| 阶段 | 状态 | 工具 |
|------|------|------|
| 当前(P0-T3 后) | 人工按本 SOP 跑 | 无自动化工具,手动 `git mv` |
| P0-T6 | pre-commit hook 串接 | `check_line_limits` + `check_openspec_indices`(本 archive 前必过) |
| P0-T8 | `/opsx:archive` 自动化 | `tools/_meta/openspec_archive.py` 实施 Step 1-3 + 5;Step 4 (design 摘要化) 半人工(工具生成模板,人工填) |

在 `openspec_archive.py` ship 前,人工执行 SHALL 严格按本 SOP — 不
可省略 step,不可调换顺序。

## 8. 实例:一次完整的 archive

假设 change `0023-foo-feature` 已完成实施。

```bash
# 1. Verify tasks
grep -c '^\- \[ \]' openspec/changes/0023-foo-feature/tasks.md
# → 0  ✓

# 2. Spec delta merge(人工 edit openspec/specs/foo/spec.md)
# 把 changes/0023-foo-feature/specs/foo/spec.md 中 SHALL 合入

# 3. 行数复检
.venv/bin/python -m tools._meta.check_line_limits openspec/specs/foo/
# → all pass  ✓

# 4. 摘要化 design.md
$EDITOR openspec/changes/0023-foo-feature/design.md
# 删细节,留 verdict + retrospective

# 5. git mv
git mv openspec/changes/0023-foo-feature openspec/changes/archive/0023-foo-feature

# Commit
git add openspec/specs/foo/spec.md openspec/changes/archive/0023-foo-feature/
git commit -m "openspec archive: 0023-foo-feature (P1-T7) ..."
```

## 9. Cross-references

- 主 spec → [`./spec.md`](./spec.md)(invariant #8 由本文落实)
- Spec delta layout → [`./file-layout.md`](./file-layout.md) 第 2.3 节
- 行数阈值复检 → [`./thresholds.md`](./thresholds.md) 表 1
- 合入后内容归属 → [`./content-boundary.md`](./content-boundary.md) 第 3.2 节(ADR 跨边界)
