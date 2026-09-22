---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
parent: ./spec.md
---

# Thresholds — 行数与字节阈值

> 治理 [`./spec.md`](./spec.md) invariant #2 / #3 / #4 / #5 / #11。
> 规定 OpenSpec artifact 与 docs/ 各类 markdown 的行数与字节硬上限,
> 以及 bypass 协议。

## 1. 阈值哲学

三档分级:
- **警告(WARNING)**:接近上限,该评估预拆 — pre-commit hook **不**
  reject,只提示
- **必拆(MUST SPLIT)**:命中阈值 — pre-commit hook **REJECT**;必须先
  拆 subtopic / 拆 `design/` 目录才能 commit
- **Hard fail(REJECT)**:任何 enforcement 失效或显式 bypass 后的兜底
  上限,SKIP_HOOK **不能**越过 hard fail — 越过的 commit 视为违反 spec

阈值数字 SHALL 由 `tools/_meta/check_line_limits.py`(P0-T4 后落地)
`PATTERNS` 注册表实现,本表是 source of truth。

## 2. 表 1 — 文件行数阈值

| 文件类型 (glob)                                | 警告 | 必拆 | Hard fail |
|------------------------------------------------|------|------|-----------|
| `openspec/specs/**/spec.md`(主入口)          | 250  | 300  | 350       |
| `openspec/specs/**/<subtopic>.md`              | 350  | 400  | 500       |
| `openspec/changes/**/proposal.md`              | 250  | 300  | 350       |
| `openspec/changes/**/design.md`(顶层 / 单文件)| 400  | 500  | 600       |
| `openspec/changes/**/design/*.md`              | 350  | 400  | 500       |
| `openspec/changes/**/tasks.md`(顶层 / 单文件) | 400  | 500  | 600       |
| `openspec/changes/**/tasks/*.md`               | 350  | 400  | 500       |
| `openspec/changes/**/specs/**/spec.md`(delta)| 250  | 300  | 350       |
| `openspec/project.md`                          | 250  | 300  | 350       |
| `docs/paradigms/**/*.md`                       | 400  | 500  | 500       |
| `docs/{runs,history,research}/**/*.md`         | 400  | 500  | 500       |
| `docs/now.md`(LIVE 状态快照,P1 后)           | 250  | 300  | 350       |
| `AGENTS.md`(repo 根)                         | 150  | 200  | 200       |

### 2.1 阈值选择理由

**主 spec.md 300**:索引文件不应膨胀;>300 行说明 SHALL 太多或没拆
subtopic。350 hard fail 留一档容错。

**Subtopic 400**:单一主题深入展开的合理上限;>400 说明该主题本身需
要再拆维度。500 hard fail。

**Proposal 300 / Design 500 / Tasks 500**:proposal 是 "why + what" 摘
要,300 行足够;design 容许架构图 + 多 tradeoff,500;tasks 含完整
checkbox 列表,500。

**Spec delta 300**:与主 spec.md 同级别;>300 说明本 change 改的太多,
应拆为多 change。

**`docs/paradigms/**` 500**:实验记录可以长,但 500 是可读性上限;超
过应拆 sub-page(如 `runs/r001.md` + `runs/r002.md`)。

**AGENTS.md 200**:repo 根级开发流程必须保持极简，>200 是
红线。30 KB 字节硬上限。

## 3. 表 2 — 字节阈值

| 文件类型              | Hard fail bytes |
|-----------------------|-----------------|
| `AGENTS.md`           | 30 KB           |
| 其他 markdown         | 50 KB           |

字节阈值与行数阈值 OR 关系:任一命中即 REJECT。多用于:
- 大表格、大代码块 → 行少但字节多
- 长行(英文段落)→ 行少但字节多

## 4. SHALL

1. 表 1 / 表 2 所有数字 SHALL 由 `tools/_meta/check_line_limits.py`
   `PATTERNS` 注册表实现,本表与代码同步;改阈值 SHALL 走 OpenSpec change。

2. pre-commit hook **必拆** 触发 SHALL REJECT commit,退出非零,
   stderr 输出违反文件 + 当前行数 + 阈值。

3. **Hard fail** 是兜底阈值:即使 `SKIP_*_HOOK=1` bypass,文件越过
   hard fail 视为违反本 spec,后续 archive / review SHALL 拒绝。

4. 新增 capability spec 时 SHALL 检查 [`./file-layout.md`](./file-layout.md)
   Layout 1 + 本表"主入口 / subtopic"两档。

## 5. Bypass 协议

| 环境变量                       | 跳过的 hook                              |
|--------------------------------|------------------------------------------|
| `SKIP_LINE_LIMIT_HOOK=1`       | 行数检查(本 spec 表 1)                  |
| `SKIP_RUFF_HOOK=1`             | Python ruff format check                 |
| `SKIP_GOFMT_HOOK=1`            | Go gofmt check                           |
| `SKIP_OPENSPEC_INDEX_HOOK=1`   | Subtopics 索引一致性(P0-T5 后落地)     |

### 5.1 何时允许 bypass

- 大型 mechanical refactor 中间状态(单 commit 内文件超阈值,
  后续 commit 立即拆)
- Hotfix 必须立即合入,拆 subtopic 时间窗不允许
- 工具本身 bug(误报)— 必须同步 file issue

### 5.2 何时**不**允许 bypass

- 日常 spec / docs 写作 — bypass 不应作 workflow 一部分
- 单纯不想拆 — 这是 spec 的核心,不允许绕过

### 5.3 Bypass commit 要求

任何带 `SKIP_*_HOOK=1` 的 commit SHALL 在 commit message body 显式说
明原因 + 后续拆分计划。格式:

```
<scope>: <summary>

[SKIP <HOOK_NAME>] <one-line 原因>
Follow-up: <一句话说明何时 / 如何拆分到合规状态>

<余下正文>
```

## 6. Inheritance 字段阈值(概述)

cfg 中可继承字段 registry 由 `tools/_meta/inheritance.py`(P0-T7 后
落地)管,字段定义包含:
- `fallback_chain`:lookup 顺序(如 `meta.device` → `train.device` →
  hard_default)
- `hard_default`:fallback 全失败时的兜底值
- `validator`:类型 / 值域检查

### 6.1 当前 registry 内容

| 字段     | Fallback chain                              | Hard default | 校验           |
|----------|---------------------------------------------|--------------|----------------|
| `device` | `meta.device` → `train.device` → hard       | `"cpu"`      | enum: cpu/cuda/mps |
| `seed`   | `meta.seed` →(no fallback)→ raise         | **无**       | int ≥ 0        |

`seed` 显式无 hard default — `meta.seed` 必填,registry resolver 缺失
seed SHALL raise,不替缺失 seed 兜底任意值。详 cfg-schema capability spec
(本 task 不展开)。

### 6.2 新字段加入

新字段(如 `dtype`、`log_level`、`checkpoint_root`)加入 registry
SHALL 走 OpenSpec change:
- 改 `tools/_meta/inheritance.py` registry
- 改 cfg-schema spec 描述
- 改本表(若该字段影响 cfg 阈值)
- Migration:旧 cfg 的兼容性(默认值是否破坏现有 run)

## 7. Cross-references

- 主 spec → [`./spec.md`](./spec.md)(invariant #11 由本文落实)
- 拆分模板 → [`./file-layout.md`](./file-layout.md) 第 2.2 / 6 节
- Archive 时行数复检 → [`./archive-workflow.md`](./archive-workflow.md) Step 3
- 工具落地 → `tools/_meta/check_line_limits.py`(P0-T4)
