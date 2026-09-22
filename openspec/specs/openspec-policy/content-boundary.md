---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
parent: ./spec.md
---

# Content Boundary — openspec/ vs docs/ 内容归属

> 治理 [`./spec.md`](./spec.md) invariant #1。
> 规定哪些内容落 `openspec/`、哪些落 `docs/`、跨边界内容如何处理。

## 1. 核心原则

**两类内容,泾渭分明**:

| 类型 | 归属 | 句式特征 |
|------|------|----------|
| 系统的约束 / 当前状态 / 决策 | `openspec/` | SHALL / MUST / IS / SHOULD |
| 实验数据 / 观察 / 推导 / 复盘 | `docs/` | "我们发现 / 我们尝试 / 我们学到" |

更直白:
- **"系统现在是什么 / 必须是什么"** → `openspec/`
- **"我们发现了什么 / 我们尝试了什么 / 我们学到了什么"** → `docs/`

## 2. 判定矩阵

| 内容示例 | 归属位置 | 判定理由 |
|----------|----------|----------|
| "AZ network 用 KL policy head" | `openspec/specs/paradigm-az/network.md` | 系统当前状态(IS) |
| "AZ + BC warm-start 把 BC 0.75 摧毁到 0.17" | `docs/paradigms/az/postmortems/r010.md` | 实验发现 |
| "C1v7 struct_readout 引入" | `docs/paradigms/az/architecture/c1v7.md` | 历史架构演化 |
| "Stage 3 ceiling F1-D2 = 0.344" | `docs/paradigms/ppo/ablations.md` | 实验数据 |
| ADR-0009 closure decision | `openspec/changes/archive/0009-rl-paradigm-terminus/` | 决策记录(archived change) |
| ADR-0011 pool versioning | `openspec/changes/archive/0011-pool-versioning/` | 决策 + 落地后规约 |
| run-specific notes(r009 ckpt cfg)| `docs/runs/registry.md` + `docs/paradigms/bc/runs/r009.md` | 实验性档案 |
| ADR-0019 DSL v6 strict refactor | `openspec/changes/archive/0019-dsl-v6/` + spec delta 合入 `openspec/specs/engine-dsl/` | 决策 + spec 修订 |
| 当前在做什么(本周做哪些事) | `docs/now.md`(LIVE) | 状态快照,不是规约 |
| Paradigm landscape recap | `docs/paradigms/README.md` + `openspec/changes/archive/0020-paradigm-recap/` | dossier 在 docs;决策在 openspec |
| DSL counter+hook 模型 SHALL | `openspec/specs/engine-dsl/spec.md` | 系统恒定约束 |
| DSL spike 2 silent_invoke 提案 | `openspec/changes/<id>/proposal.md` → archive | 决策提案 |
| Inheritance registry 当前字段 | `openspec/specs/cfg-schema/inheritance.md` | 当前 registry 状态(IS) |
| 某 ablation 表 + 结论 | `docs/paradigms/<name>/ablations/<sweep>.md` | 实验记录 |
| 训练完跑 gauntlet 的纪律 | `openspec/specs/training-workflow/spec.md`(假定后续 capability)| SHALL 句 |
| “开发工具怎么用” | `AGENTS.md`(repo 根)| 开发流程，不是 spec |

## 3. 关键区分线

### 3.1 SHALL / IS vs 观察 / postmortem

**SHALL / IS 句**(落 `openspec/`):
- "engine SHALL NOT know HP / energy / elements"
- "AZ self-play SHALL use determinize-resample sampling"
- "Run 目录命名 SHALL follow `YYYYMMDDHHMM_<label>/`"
- "Inheritance `device` field SHALL fall back to `meta.device` →
  `train.device` → hard default `cpu`"

**观察 / 数据 / 假设 / 推导 / postmortem**(落 `docs/`):
- "r010 BC warm-start 让 AZ 学崩了,从 BC 0.75 降到 0.17"
- "F1-D2 ceiling 实测 ≈ 0.344,与理论预测 0.40 差距由 PPO oscillation 解释"
- "C1v7 struct_readout 是 pool 零空间 saturation 的 workaround"
- "ADR-0019 strict refactor 跨 17 commits ship"

### 3.2 ADR 跨边界处理

ADR(Architecture Decision Record)既是"决策"(openspec)也是"历史
档案"(docs)。处理方式:

1. **新 ADR**:作 OpenSpec change 落地
   - `openspec/changes/<id>/proposal.md`:why + alternatives 摘要
   - `openspec/changes/<id>/design.md`:tradeoff 详述 + 决策上下文
   - `openspec/changes/<id>/specs/<X>/spec.md`:spec delta(SHALL 变化)
   - 完成后 `/opsx:archive` → `openspec/changes/archive/<id>/`,
     spec delta 合入 `openspec/specs/<X>/spec.md`

2. **历史 ADR(旧 `docs/2_decisions/adr-NNNN-*.md`)**:
   - 已发生的决策不重写为 change(成本高、无价值)
   - 内容归属:决策内容应已反映在当前 `openspec/specs/`(若未反映,
     在新 change 中"承接"该 ADR 的 spec 影响)
   - 历史 ADR 文件 SHOULD 迁到 `docs/history/adr/` 或保留原位作为
     "历史档案"

3. **复盘**:任何 ADR 关联的实验过程、踩坑、推导路径 → `docs/paradigms/<name>/postmortems/`
   或 `docs/history/`

### 3.3 Run notes 跨边界

Run notes 同时含 IS 句 + 观察:
- IS 部分(cfg / ckpt 路径 / 评测协议)→ `docs/runs/registry.md`
  (runs-registry capability spec 治理其字段 schema)
- 观察部分(metrics 曲线、ablation 表、postmortem)→
  `docs/paradigms/<name>/runs/<run-id>.md`

## 4. SHALL

1. `openspec/` 内容 SHALL 以 SHALL/SHOULD/MAY 句式为主,SHALL avoid
   长篇 narrative / 实验数据 / "我们尝试" 句式。

2. `docs/` 内容 MAY 使用自由 markdown,无 SHALL 要求,无句式约束。

3. 跨边界内容(如 ADR)SHALL 通过 OpenSpec change 落地:
   - proposal + design 写决策上下文
   - spec delta 落 spec
   - 关联 docs 文件(postmortem / 复盘)作为补充材料

4. `openspec/project.md` SHALL 描述 project-level "IS / SHALL",不
   描述 "本周做什么" — 后者落 `docs/now.md`。

5. 不允许在 `openspec/specs/**` 内放实验数据表、postmortem 段;
   不允许在 `docs/paradigms/**` 内放 SHALL invariant 列表。

## 5. 灰区与判定流程

遇到归属灰区,按以下流程判定:

```
Step 1: 这段内容是 "系统约束 / 当前状态"(IS)
        还是 "我们的发现 / 尝试"(experience)?
   ├── IS  → openspec/
   │       └── 是 capability-level 约束?       → specs/<cap>/
   │           是 change-level 提案?            → changes/<id>/
   │           是 project-level 立约?           → project.md
   └── experience → docs/
           └── 是 paradigm 实验?               → paradigms/<name>/
               是跨 paradigm 复盘?             → history/
               是当前进度?                    → now.md
               是 run 索引?                   → runs/

Step 2: 内容混合 IS + experience?
   → 拆!IS 部分入 openspec;experience 部分入 docs;
     两者交叉引用(relative path)。
```

## 6. 反例:常见误归属

| 误归属内容(WRONG) | 正确归属 |
|---------------------|----------|
| `openspec/specs/paradigm-az/postmortem.md`(r010 实验复盘) | `docs/paradigms/az/postmortems/r010.md` |
| `openspec/specs/paradigm-az/spec.md` 内含 "实测 F1-D2=0.344" | 只 SHALL 句,数据落 dossier |
| `docs/paradigms/az/spec.md`(命名错;dossier 没有 spec.md 概念) | dossier 用 `README.md`;SHALL 落 `openspec/specs/paradigm-az/spec.md` |
| `docs/now.md` 列 "AZ network SHALL ..."(SHALL 句不属状态快照) | SHALL 落 `openspec/specs/`;now.md 只列本周进度 |
| `openspec/project.md` 写 "r009 BC retrain in progress" | progress 落 `docs/now.md`;project.md 只写稳定立约 |

## 7. 迁移路线(对历史 docs/)

现有 `docs/` 结构(`0_status / 1_specs / 2_decisions / 3_plans / 4_runs
/ 5_history`)在 OpenSpec 迁移过程中分两类:
- **`1_specs/` 内容**:整体迁向 `openspec/specs/<capability>/`(P1+ task)
- **`2_decisions/` 内容**:`docs/history/adr/` 保留原文件;新决策走 OpenSpec change
- **`3_plans/`**:roadmap 迁向 `docs/now.md`(LIVE)+ `docs/plans/`
- **`4_runs/`**:迁向 `docs/runs/`(runs-registry spec 治理)
- **`5_history/`**:迁向 `docs/history/`

具体迁移由 P1+ 各 capability 落地时携带 OpenSpec change 执行,本 spec
只规约**目标**结构,不规约**迁移步骤**(那是 change 的责任)。

## 8. Cross-references

- 主 spec → [`./spec.md`](./spec.md)(invariant #1 由本文落实)
- Paradigm dossier layout → [`./file-layout.md`](./file-layout.md) 第 3 节
- Archive 时合入 spec → [`./archive-workflow.md`](./archive-workflow.md) Step 2
- Project-level 立约 → [`../../project.md`](../../project.md)
