---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
parent: ./spec.md
---

# File Layout — OpenSpec artifact 标准目录布局

> 治理 [`./spec.md`](./spec.md) invariant #2 / #4 / #5 / #10。
> 规定每种 OpenSpec artifact 的标准目录结构,以及何时预拆 vs 后拆。

## 1. Layout 1 — Capability spec

`openspec/specs/<capability>/` 是 capability spec 目录。每个 capability
一个目录,目录名 SHALL kebab-case(如 `openspec-policy`、`cfg-schema`、
`paradigm-az`)。

### 1.1 标准结构

```
openspec/specs/<capability>/
├── spec.md (≤300 行)                  ★必有
│   - Front matter (last_updated / status / schema_version / capability)
│   - Purpose
│   - Scope (in / out)
│   - Core SHALL invariants (5-15 条编号)
│   - Subtopics 索引(指向同目录 sibling)
│   - Cross-references(指向 project.md / 其他 capability / 工具)
│   - Status (created / version / revision triggers)
├── <subtopic-a>.md (≤400 行)          按需(0~N 个)
├── <subtopic-b>.md (≤400 行)
└── examples/                          按需
    ├── <case-1>.md                    Gherkin / 表格 / code snippet
    └── <case-2>.md
```

### 1.2 命名

- `spec.md` 是固定文件名。**不允许** `spec.md.v1`、`spec.md.old`、
  `spec-new.md` 等多版本并存 — 历史用 git。
- Subtopic 文件名 SHALL kebab-case + `.md` 后缀,与索引段文字
  对应。约定常用名:`file-layout.md` / `thresholds.md` /
  `content-boundary.md` / `archive-workflow.md` / `network.md` /
  `training-loop.md` / `evaluation.md`。
- `examples/` 子目录可选,放具体场景说明、Gherkin 测试预言、
  数据示例。不参与索引强制(thresholds 不算 subtopic)。

### 1.3 Front matter 约定

每个 markdown 文件首行 SHALL 有 YAML front matter,至少含:
```yaml
---
last_updated: YYYY-MM-DD
status: LIVE | DRAFT | DEPRECATED
schema_version: <int>
---
```
Subtopic 文件 SHOULD 额外加 `parent: ./spec.md` 标注从属关系。
Capability 主 `spec.md` SHOULD 加 `capability: <name>` 显式声明。

## 2. Layout 2 — Change

`openspec/changes/<change-id>/` 是 active change 目录。Change ID 推荐
`<NNNN>-<slug>` 或 `<slug>` 两种风格,与 `/opsx:propose` 输出一致。

### 2.1 标准结构

```
openspec/changes/<change-id>/
├── proposal.md (≤300 行)              ★必有
│   - Why(动机 / 现状 pain point)
│   - What(≤5 条 bullet,本 change 干啥)
│   - Affected specs(列出会改 / 加的 capability spec)
│   - Out of scope(防 scope creep)
├── design.md (≤500 行)                ★必有(顶层或单文件形式)
│   - Architecture(本 change 引入的结构)
│   - Migrations(如有)
│   - Tradeoffs(选项对比 / 决策理由)
│   - Risks(失败模式 / 回滚预案)
├── tasks.md (≤500 行)                 ★必有(顶层或单文件形式)
│   - Task list 带 checkbox(`- [ ]` / `- [x]`)
│   - 每 task 标 LOC 预估 / 依赖关系
└── specs/<affected-capability>/spec.md(≤300 行)
    Spec delta:本 change 对该 capability 的修订片段
```

### 2.2 design.md / tasks.md 拆分

单文件接近 500 行 → 拆为目录形式:

```
design.md 拆分后:
├── design.md (≤300 行,顶层导览)
└── design/
    ├── architecture.md  (≤400)
    ├── migrations.md    (≤400)
    ├── tradeoffs.md     (≤400)
    └── risks.md         (≤400)

tasks.md 拆分后:
├── tasks.md (≤200 行,phase 索引 + 总进度)
└── tasks/
    ├── phase1-<slug>.md (≤400)
    ├── phase2-<slug>.md (≤400)
    └── ...
```

### 2.3 Spec delta

`specs/<affected>/spec.md` 是 change 对一个或多个 capability spec
的修订片段,SHALL ≤ 300 行,只描述**本 change 引入的 SHALL 变化**:

- **Add**:新加的 SHALL 行,标 `[ADD]`
- **Modify**:改的 SHALL 行,前后对照,标 `[MODIFY]`
- **Remove**:删的 SHALL 行,理由必写,标 `[REMOVE]`

Archive 时按 [`./archive-workflow.md`](./archive-workflow.md) Step 2
合并到 `openspec/specs/<capability>/spec.md`。

## 3. Layout 3 — Paradigm dossier

Paradigm dossier 存放 paradigm 的**实验性记录**,在 `docs/paradigms/`
而非 `openspec/`(因为是"我们尝试了什么 / 学到了什么",不是规约 —
详 [`./content-boundary.md`](./content-boundary.md))。本 spec 仍给
出标准 layout 以保持目录可索引性。

### 3.1 标准结构

```
docs/paradigms/<name>/
├── README.md (≤200 行)        概述 + verdict + 入口导航
├── runs/                      run 时间序记录
│   ├── r001.md
│   ├── r002.md
│   └── ...
├── ablations/                 ablation sweep,如有
│   └── <sweep-id>.md
├── architecture/              架构演化片段
│   └── c1v7.md                (例:struct_readout 引入)
├── postmortems/               失败分析 / 复盘
│   └── r010.md
└── notes.md (≤300 行)         零散观察(不够独立成文件的)
```

### 3.2 SHALL

- Paradigm dossier 内文件遵循 [`./thresholds.md`](./thresholds.md)
  表 1 的 `docs/paradigms/**/*.md` 行,≤ 500 行
- `README.md` SHALL 作为入口,带 verdict 段(成功 / 失败 / closed)
  + 关键 run 索引
- 子目录命名 SHALL 与本节模板一致(`runs/` / `ablations/` /
  `architecture/` / `postmortems/`)以保跨 paradigm 一致性
- Paradigm 决策(SHALL/IS 句:"AZ network 用 KL policy head")
  SHALL 落 `openspec/specs/paradigm-<name>/`,**不**落 dossier

## 4. Layout 4 — Active vs Archived change

Active change(进行中)路径:
```
openspec/changes/<change-id>/
```

Archived change(完成 + `/opsx:archive` 跑过)路径:
```
openspec/changes/archive/<change-id>/
```

`git mv` 整目录,保留全部历史。archive 后:
- `tasks.md` 全 checkbox checked(invariant by SOP step 1)
- `design.md` 已摘要化(≤ 200 行,带 retrospective verdict)
- `specs/` 子目录内 spec delta 已 merge 到对应 capability spec
- Proposal 保留原样,作为"当时的提案"历史快照

详 [`./archive-workflow.md`](./archive-workflow.md)。

## 5. 通用约束

### 5.1 索引强制

主 `spec.md` SHALL 维护 `## Subtopics` 段,列出本目录下所有 subtopic
markdown 文件(不含 `examples/` 子目录、不含 `spec.md` 自身)。

格式:
```markdown
## Subtopics

- [Short name](./<file>.md) — 一行说明
```

新增 / 删除 subtopic SHALL 同步更新索引。`tools/_meta/check_openspec_indices.py`
(P0-T5 后落地)校验:
- 索引列出的每个文件存在
- 目录下每个 non-example markdown 文件被索引

### 5.2 命名约束

- Subtopic 文件名:kebab-case + `.md`
- Change ID:kebab-case + `.md` 内含 / 数字-slug 风格
- 不允许中文文件名(filesystem 跨平台兼容)
- 不允许空格、大写、下划线

### 5.3 多版本禁止

不允许任何 `<name>.md.v1`、`<name>.md.old`、`<name>-new.md`、
`<name>-draft.md` 形式的版本副本。历史完全交给 git:
- 看历史:`git log --follow <file>`
- 看 diff:`git diff <commit> <file>`
- 回滚:`git revert` 或新 change

## 6. 何时拆分:预拆 vs 后拆

### 6.1 预拆(写之前就拆)

写之前已经清楚 ≥ 3 个 subtopic → 直接按 Layout 1 起步,主 spec.md
立即建好 Subtopics 段,各 subtopic 文件并行写。

典型场景:
- 本 spec(openspec-policy)起步即知 4 subtopic → 预拆
- 复杂 capability(如 paradigm-az,有 network / training-loop /
  evaluation 三轴正交)→ 预拆

### 6.2 后拆(单文件接近阈值时拆)

单文件接近 [`./thresholds.md`](./thresholds.md) 警告区(≥ 80%
阈值)→ 评估是否抽 subtopic。pre-commit hook 在 100% 阈值
REJECT,届时 **必须** 拆才能 commit。

拆分原则:
- 按正交 dimension 切(不是按章节序号切)
- 每个 subtopic 自成一个可被独立引用的 invariant 集合
- 拆后主 spec.md 留 SHALL 概要,subtopic 写细则 + 例子 + 矩阵

### 6.3 何时**不**拆

- 文件 < 250 行且无新增内容预期 → 不拆
- 内容是单一连续推导(如一个数学证明)→ 不拆(拆了反而难读)
- 跨 capability 内容 → 不是"拆 subtopic",是"建新 capability spec"

## 7. Cross-references

- 主 spec → [`./spec.md`](./spec.md)
- 阈值表 → [`./thresholds.md`](./thresholds.md)
- 内容归属 → [`./content-boundary.md`](./content-boundary.md)
- Archive 流程 → [`./archive-workflow.md`](./archive-workflow.md)
- Project-level layout → [`../../project.md`](../../project.md)
